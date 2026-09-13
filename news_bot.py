import os
import re
import time
import subprocess
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

YOUTUBE_SHORTS_FEEDS = [
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSHvJJ_JLWvmy5_VqqmB65mDg",  # CNBC
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH16niRr50-MSBwiO3YDb3RA",  # BBC
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSHhirEOpgFCupSTNZv4665YA",  # Bloomberg
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSHknLrEdhRCp1aegoMqRaCZg",  # DW News
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH_gUM8rL-Lzy6ZRv9SvwGWA",  # ABC News
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH5d_FhUa3kPqmGkGg5b2g",    # WION
    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSHCEAZeUIeJs0IjQiqTCdVSIg"   # Yahoo Finance
]

# Helper function to convert any video into 100% Instagram-ready 9:16 Reel
def convert_to_instagram_reel(input_file, output_file):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    # Scales to 1080x1920 vertical with black padding if needed, enforces yuv420p and aac
    cmd = [
        ffmpeg_exe, "-y",
        "-i", input_file,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart",
        output_file
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# ================= 2. FETCH LATEST SHORT NEWS VIDEO =================
def get_latest_news_short():
    posted_links = set()
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            posted_links = set(line.strip() for line in f if line.strip())

    raw_path = "raw_download.mp4"
    final_reel_path = "news_video.mp4"
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': raw_path,
        'ffmpeg_location': ffmpeg_exe,
        'merge_output_format': 'mp4',
        'quiet': True,
        'noplaylist': True,
        'match_filter': yt_dlp.utils.match_filter_func("duration <= 90")
    }

    for feed_url in YOUTUBE_SHORTS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                video_url = entry.link
                if video_url not in posted_links:
                    print(f"\nTargeting: {entry.title}\nURL: {video_url}")

                    for f in [raw_path, final_reel_path]:
                        if os.path.exists(f):
                            try:
                                os.remove(f)
                            except Exception:
                                pass

                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([video_url])
                    except Exception:
                        continue

                    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 15000:
                        print("Converting video to standard Instagram 9:16 vertical Reel...")
                        convert_to_instagram_reel(raw_path, final_reel_path)
                        
                        with open(TRACKER_FILE, "a", encoding="utf-8") as f:
                            f.write(video_url + "\n")

                        title = entry.title
                        description = getattr(entry, "summary", title)
                        return title, description, video_url, final_reel_path
        except Exception as e:
            continue

    return None, None, None, None

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
        model="openai/gpt-oss-20b",
        temperature=0.7,
    )

    return chat_completion.choices[0].message.content.strip()

# ================= 4. BUFFER GRAPHQL VIDEO PUBLISH =================
def publish_to_buffer(video_path, caption):
    print("Uploading standardized Reel to Cloudinary...")
    upload_res = cloudinary.uploader.upload(
        video_path,
        resource_type="video"
    )
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
    print("[1/3] Searching, downloading and standardizing News Reel...")
    title, desc, url, video_file = get_latest_news_short()

    if video_file:
        print(f"Standardized Reel Ready: {title}")

        print("[2/3] Generating AI caption with Groq...")
        caption = generate_ai_caption(title, desc)
        print("Caption generated successfully.")

        print("[3/3] Uploading & publishing video to platforms...")
        publish_to_buffer(video_file, caption)
        print("\nReal news video published successfully!")
    else:
        print("Done. No new videos found in this cycle.")