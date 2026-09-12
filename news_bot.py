import os
import re
import random
import requests
import textwrap
import feedparser
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import cloudinary
import cloudinary.uploader
from groq import Groq
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ================= 1. CONFIGURATION =================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BUFFER_TOKEN = os.getenv("BUFFER_TOKEN")

CHANNEL_IDS = [
    "6aa38c78cd8b9c702c4a94c0",  # Instagram
    "6aa39a63cd8b9c702c4b0364",  # LinkedIn
    "6aa39a25cd8b9c702c4affd3"   # Threads
]

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

client = Groq(api_key=GROQ_API_KEY)
TRACKER_FILE = "posted_links.txt"

# Dynamic styling themes
COLOR_THEMES = [
    {"accent": "#E11D48", "tag": "MARKET WATCH"},
    {"accent": "#2563EB", "tag": "GLOBAL UPDATE"},
    {"accent": "#059669", "tag": "ECONOMY BRIEFS"},
    {"accent": "#D97706", "tag": "FINANCE ALERT"},
    {"accent": "#7C3AED", "tag": "TECH PULSE"}
]

# ================= 2. MULTI-FEED GLOBAL NEWS FETCHING =================
def get_latest_news():
    feed_urls = [
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=business&format=rss",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en"
    ]

    posted_links = set()
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            posted_links = set(line.strip() for line in f if line.strip())

    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if entry.link not in posted_links:
                    img_url = None
                    if 'media_content' in entry and entry.media_content:
                        img_url = entry.media_content[0].get('url')
                    elif 'media_thumbnail' in entry and entry.media_thumbnail:
                        img_url = entry.media_thumbnail[0].get('url')
                    elif 'description' in entry:
                        matches = re.findall(r'<img[^>]+src="([^">]+)"', entry.description)
                        if matches:
                            img_url = matches[0]

                    with open(TRACKER_FILE, "a", encoding="utf-8") as f:
                        f.write(entry.link + "\n")
                    return entry.title, entry.link, img_url
        except Exception:
            continue

    raise Exception("Sabhi global sources ki taaza news pehle se post ho chuki hain.")

# ================= 3. AI SUMMARY (GROQ) =================
def generate_ai_content(raw_title):
    prompt = f"""
    News: {raw_title}
    
    Format requirements:
    1. A punchy headline in 6-8 words (ALL CAPS).
    2. A crisp summary in 25-30 words.
    3. An engaging social media caption with 4 global business hashtags.
    
    Return output strictly separated by '|||':
    HEADLINE ||| SUMMARY ||| CAPTION
    """

    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="openai/gpt-oss-120b",
        temperature=0.7,
    )

    full_text = chat_completion.choices[0].message.content.strip()
    parts = full_text.split("|||")
    return parts[0].strip(), parts[1].strip(), parts[2].strip()

# ================= 4. IMAGE GENERATION =================
def create_news_card(headline, summary, bg_img_url):
    width, height = 1080, 1350
    theme = random.choice(COLOR_THEMES)

    image = None
    if bg_img_url:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(bg_img_url, headers=headers, timeout=8)
            if res.status_code == 200:
                bg = Image.open(BytesIO(res.content)).convert("RGB")
                scale = max(width / bg.width, height / bg.height)
                nw, nh = int(bg.width * scale), int(bg.height * scale)
                bg = bg.resize((nw, nh), Image.Resampling.LANCZOS)
                x_crop = (nw - width) // 2
                y_crop = (nh - height) // 2
                image = bg.crop((x_crop, y_crop, x_crop + width, y_crop + height))
        except Exception as e:
            print(f"[Notice] Could not load image ({e}). Using solid theme.")

    if not image:
        image = Image.new("RGB", (width, height), color=(15, 23, 42))

    draw = ImageDraw.Draw(image)

    try:
        font_tag = ImageFont.truetype("arialbd.ttf", 26)
        font_head = ImageFont.truetype("arialbd.ttf", 62)
        font_body = ImageFont.truetype("arial.ttf", 34)
        font_brand = ImageFont.truetype("arialbd.ttf", 26)
    except Exception:
        font_tag = font_head = font_body = font_brand = ImageFont.load_default()

    margin = 80
    box_height = 600

    overlay = Image.new("RGBA", (width, box_height), (10, 15, 25, 235))
    image.paste(overlay, (0, height - box_height), overlay)

    content_top = height - box_height + 60

    draw.rectangle([(margin, content_top), (margin + 260, content_top + 50)], fill=theme["accent"])
    draw.text((margin + 20, content_top + 10), theme["tag"], fill="#FFFFFF", font=font_tag)

    wrapped_headline = textwrap.fill(headline, width=24)
    head_y = content_top + 75
    draw.text((margin, head_y), wrapped_headline, fill="#FFFFFF", font=font_head, spacing=14)

    head_lines = wrapped_headline.count("\n") + 1
    divider_y = head_y + (head_lines * 75) + 15
    draw.line([(margin, divider_y), (margin + 160, divider_y)], fill=theme["accent"], width=5)

    wrapped_summary = textwrap.fill(summary, width=44)
    sum_y = divider_y + 25
    draw.text((margin, sum_y), wrapped_summary, fill="#D1D5DB", font=font_body, spacing=12)

    draw.text((margin, height - 55), "@rnne_ws  •  Global Business Daily", fill="#9CA3AF", font=font_brand)

    output_path = "final_post.jpg"
    image.save(output_path, quality=95)
    return output_path

# ================= 5. BUFFER GRAPHQL DIRECT PUBLISH =================
def publish_to_buffer(image_path, caption):
    upload_res = cloudinary.uploader.upload(image_path)
    image_url = upload_res["secure_url"]
    print(f"Uploaded Image URL: {image_url}")

    graphql_url = "https://api.buffer.com"
    clean_token = BUFFER_TOKEN.replace("Bearer ", "").strip() if BUFFER_TOKEN else ""

    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json"
    }

    mutation = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post {
            id
            status
          }
        }
        ... on MutationError {
          message
        }
      }
    }
    """

    for channel_id in CHANNEL_IDS:
        post_input = {
            "channelId": channel_id,
            "text": caption,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": [{"image": {"url": image_url}}]
        }

        # Instagram channel metadata
        if channel_id == "6aa38c78cd8b9c702c4a94c0":
            post_input["metadata"] = {
                "instagram": {
                    "type": "post",
                    "shouldShareToFeed": True
                }
            }

        response = requests.post(
            graphql_url,
            headers=headers,
            json={"query": mutation, "variables": {"input": post_input}}
        )
        print(f"Buffer GraphQL response for {channel_id}: HTTP {response.status_code} - {response.text}")

# ================= EXECUTION =================
if __name__ == "__main__":
    print("[1/4] Fetching latest global news with image...")
    raw_title, link, img_url = get_latest_news()
    print("Found:", raw_title)
    print("Image detected:", img_url)

    print("[2/4] Processing text with Groq (Free)...")
    headline, summary, caption = generate_ai_content(raw_title)

    print("[3/4] Rendering professional news graphic...")
    img_path = create_news_card(headline, summary, img_url)

    print("[4/4] Uploading & publishing via Buffer...")
    publish_to_buffer(img_path, caption)
    print("\nProcess finished successfully!")