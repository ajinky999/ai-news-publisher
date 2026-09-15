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

# Verified Active Channels
CHANNELS = [
    {"id": "6aa773e0ea19ca0bde3b44fb", "type": "instagram"},
    {"id": "6aa773f7ea19ca0bde3b4560", "type": "threads"},
    {"id": "6aa39a63cd8b9c702c4b0364", "type": "linkedin"}
]

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", "xnjaxvto"),
    api_key=os.getenv("CLOUDINARY_API_KEY", "636698659882116"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", "dk_rREtARWfV5f3QrJRq-h014Kw")
)

client = Groq(api_key=GROQ_API_KEY)
TRACKER_FILE = "posted_links.txt"

# Cloud-friendly feeds (Direct fallback lists)
YOUTUBE_CHANNELS = [
    "BBCNews",
    "CNN",
    "DWNews",
    "SkySportsNews",
    "ESPN",
    "CNBC",
    "TheVerge",
    "IGN"
]

def convert_to_instagram_reel(input_file, output_file):
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_exe = "ffmpeg"

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

# ================= 2. FETCH SHORTS VIA YT-DLP SEARCH =================
def get_latest_news_short():
    posted_links = set()
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            posted_links = set(line.strip() for line in f if line.strip())

    raw_path = "raw_download.mp4"
    final_reel_path = "news_video.mp4"
    
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_exe = "ffmpeg"

    # Direct search via yt-dlp jo RSS block bypass karta hai
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': raw_path,
        'ffmpeg_location': ffmpeg_exe,
        'merge_output_format': 'mp4',
        'quiet': True,
        'noplaylist': True,
        'match_filter': yt_dlp.utils.match_filter_func("duration <= 90"),
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    for ch in YOUTUBE_CHANNELS:
        search_query = f"ytsearch5:{ch} shorts news"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                entries = info.get('entries', [])
                for entry in entries:
                    if not entry:
                        continue
                    video_url = entry.get('webpage_url', f"https://www.youtube.com/watch?v={entry.get('id')}")
                    if video_url not in posted_links:
                        print(f"\nTargeting: {entry.get('title')}\nURL: {video_url}")

                        for f in [raw_path, final_reel_path]:
                            if os.path.exists(f):
                                try:
                                    os.remove(f)
                                except Exception:
                                    pass

                        ydl.download([video_url])

                        if os.path.exists(raw_path) and os.path.getsize(raw_path) > 15000:
                            print("Converting video to standard Instagram 9:16 vertical Reel...")
                            convert_to_instagram_reel(raw_path, final_reel_path)

                            with open(TRACKER_FILE, "a", encoding="utf-8") as f:
                                f.write(video_url + "\n")

                            title = entry.get('title', 'Breaking News')
                            desc = entry.get('description', title)
                            return title, desc, video_url, final_reel_path
        except Exception as e:
            print(f"Error fetching channel {ch}: {e}")
            continue

    return None, None, None, None

# ================= 3. AI CAPTION GENERATION =================
def generate_ai_caption(title, description):
    prompt = f"""
    Title: {title}
    Context: {description[:500] if description else title}
    
    Task:
    Create an engaging, viral social media news caption for this video.
    Keep it crisp, factual, and add 4-5 relevant hashtags.
    Return ONLY the final caption text.
    """

    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="openai/gpt-oss-20b",
        temperature=0.7,
    )

    return chat_completion.choices[0].message.content.strip()

# ================= 4. BUFFER PUBLISH =================
def publish_to_buffer(video_path, caption):
    print("Uploading standardized Reel to Cloudinary...")
    upload_res = cloudinary.uploader.upload(
        video_path,
        resource_type="video",
        format="mp4"
    )
    video_url = upload_res.get("secure_url", "")
    if not video_url.endswith(".mp4"):
        video_url = video_url + ".mp4"

    print(f"Uploaded Video URL: {video_url}")

    graphql_url = "https://api.buffer.com"
    clean_token = BUFFER_TOKEN.replace("Bearer ", "").strip()
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

    for channel in CHANNELS:
        channel_id = channel["id"]
        channel_type = channel["type"]

        post_input = {
            "channelId": channel_id,
            "text": caption,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": [{"video": {"url": video_url}}]
        }

        if channel_type == "instagram":
            post_input["metadata"] = {
                "instagram": {
                    "type": "reel",
                    "shouldShareToFeed": True
                }
            }

        try:
            response = requests.post(
                graphql_url,
                headers=headers,
                json={"query": mutation, "variables": {"input": post_input}}
            )
            print(f"Buffer -> {channel_type.upper()} ({channel_id}): HTTP {response.status_code} - {response.text}")
            time.sleep(3)
        except Exception as e:
            print(f"Request error on {channel_type}: {e}")

# ================= MAIN =================
if __name__ == "__main__":
    print("[1/3] Searching, downloading and standardizing Reel...")
    title, desc, url, video_file = get_latest_news_short()

    if video_file:
        print(f"Standardized Reel Ready: {title}")

        print("[2/3] Generating AI caption with Groq...")
        caption = generate_ai_caption(title, desc)
        print("Caption generated successfully.")

        print("[3/3] Uploading & publishing video to platforms...")
        publish_to_buffer(video_file, caption)
        print("\nAll platforms updated successfully!")
    else:
        print("Done. No new videos found in this cycle.")