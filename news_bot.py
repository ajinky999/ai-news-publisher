import os
import re
import feedparser
import requests
import cloudinary
import cloudinary.uploader
from groq import Groq
from dotenv import load_dotenv
import yt_dlp
import imageio_ffmpeg

load_dotenv()

# ================= 1. CONFIGURATION =================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
BUFFER_TOKEN = os.getenv("BUFFER_TOKEN", "8AQRlm4byqWtbn0HoCQwDn5odC4Ui14pb-BiMbMGScz")

CHANNEL_IDS = [
    "6aa38c78cd8b9c702c4a94c0",  # Instagram
    "6aa39a63cd8b9c702c4b0364",  # LinkedIn
    "6aa39a25cd8b9c702c4affd3"   # Threads
]

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", "xnjaxvto"),
    api_key=os.getenv("CLOUDINARY_API_KEY", "636698659882116"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", "dk_rREtARWfV5f3QrJRq-h014Kw")
)

client = Groq(api_key=GROQ_API_KEY)
TRACKER_FILE = "posted_links.txt"

# Official Shorts Playlists
YOUTUBE_SHORTS_FEEDS = [
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSHvJJ_JLWvmy5_VqqmB65mDg",  # CNBC
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH16niRr50-MSBwiO3YDb3RA",  # BBC News
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSHhirEOpgFCupSTNZv4665YA"   # Bloomberg
]

# ================= 2. FETCH LATEST SHORT NEWS VIDEO =================
def get_latest_news_short():
    posted_links = set()
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            posted_links = set(line.strip() for line in f if line.strip())

    output_path = "news_video.mp4"
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'ffmpeg_location': ffmpeg_exe,
        'merge_output_format': 'mp4',
        'quiet': False,
        'noplaylist': True,
        'match_filter': yt_dlp.utils.match_filter_func("duration <= 90")
    }

    for feed_url in YOUTUBE_SHORTS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                video_url = entry.link
                if video_url not in posted_links:
                    print(f"\nTargeting: {entry.title}\nURL: {video_url}")

                    if os.path.exists(output_path):
                        try:
                            os.remove(output_path)
                        except Exception:
                            pass

                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([video_url])
                    except Exception as dl_err:
                        print(f"Skipped ({dl_err}), trying next video...")
                        continue

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                        with open(TRACKER_FILE, "a", encoding="utf-8") as f:
                            f.write(video_url + "\n")

                        title = entry.title
                        description = getattr(entry, "summary", title)
                        return title, description, video_url, output_path
        except Exception as e:
            print(f"[Notice] Feed error: {e}")
            continue

    raise Exception("Koi nayi valid short video nahi mili. Thodi der me dobara try karein.")

# ================= 3. AI CAPTION GENERATION =================
def generate_ai_caption(title, description):
    prompt = f"""
    Title: {title}
    Context: {description}
    
    Task:
    Create an engaging, viral social media news caption for this real news video.
    Keep it crisp, factual, and add 4-5 relevant business/global hashtags.
    Return ONLY the final caption text.
    """

    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="openai/gpt-oss-120b",
        temperature=0.7,
    )

    return chat_completion.choices[0].message.content.strip()

# ================= 4. BUFFER GRAPHQL VIDEO PUBLISH =================
def publish_to_buffer(video_path, caption):
    print("Uploading real news video to Cloudinary...")
    upload_res = cloudinary.uploader.upload(video_path, resource_type="video")
    video_url = upload_res["secure_url"]
    print(f"Uploaded Video URL: {video_url}")

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
            "assets": [{"video": {"url": video_url}}]
        }

        if channel_id == "6aa38c78cd8b9c702c4a94c0":
            post_input["metadata"] = {
                "instagram": {
                    "type": "reel",
                    "shouldShareToFeed": True
                }
            }

        response = requests.post(
            graphql_url,
            headers=headers,
            json={"query": mutation, "variables": {"input": post_input}}
        )
        print(f"Buffer response for {channel_id}: HTTP {response.status_code} - {response.text}")

# ================= MAIN =================
if __name__ == "__main__":
    print("[1/3] Searching and downloading latest verified News Short/Reel...")
    title, desc, url, video_file = get_latest_news_short()
    print(f"Successfully Downloaded: {title}")

    print("[2/3] Generating AI caption with Groq...")
    caption = generate_ai_caption(title, desc)
    print("Caption generated.")

    print("[3/3] Uploading & publishing video to platforms...")
    publish_to_buffer(video_file, caption)
    print("\nReal news video published successfully!")