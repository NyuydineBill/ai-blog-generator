from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
import json
from pytube import YouTube
import os
import assemblyai as aai
import openai
from .models import BlogPost
from django.core.exceptions import ValidationError
import logging
import re
from dotenv import load_dotenv
import yt_dlp
import os
from django.conf import settings

# Load environment variables
load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)

# Securely access API keys
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

# Create your views here.
@login_required
def index(request):
    return render(request, 'index.html')


from googleapiclient.discovery import build
import os

# Load environment variables
load_dotenv()

# Get API key from environment variables
API_KEY = os.getenv("YOUTUBE_API_KEY")

def get_youtube_title(video_id):
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    request = youtube.videos().list(
        part='snippet',
        id=video_id
    )
    response = request.execute()
    title = response['items'][0]['snippet']['title']
    return title
@csrf_exempt
def generate_blog(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            yt_link = data.get('link')
            
            if not yt_link or not validate_youtube_link(yt_link):
                return JsonResponse({'error': 'Invalid YouTube link'}, status=400)

            # Get YouTube title
            title = yt_title(yt_link)
            if not title:
                return JsonResponse({'error': 'Failed to retrieve YouTube title'}, status=500)

            # Get transcript
            transcription = get_transcription(yt_link)
            if not transcription:
                return JsonResponse({'error': 'Failed to get transcript'}, status=500)

            # Use OpenAI to generate the blog
            blog_content = generate_blog_from_transcription(transcription)
            if not blog_content:
                return JsonResponse({'error': 'Failed to generate blog article'}, status=500)

            # Save blog article to database
            new_blog_article = BlogPost.objects.create(
                user=request.user,
                youtube_title=title,
                youtube_link=yt_link,
                generated_content=blog_content,
            )
            new_blog_article.save()

            # Return blog article as a response
            return JsonResponse({'content': blog_content})

        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
        except KeyError as e:
            logger.error(f"Missing key in data: {e}")
            return JsonResponse({'error': 'Missing required data'}, status=400)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)
    else:
        return JsonResponse({'error': 'Invalid request method'}, status=405)


def validate_youtube_link(link):
    youtube_regex = (
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})')
    return re.match(youtube_regex, link)

import yt_dlp

def yt_title(link):
    video_id = link.split('v=')[-1]
    return get_youtube_title(video_id)



import logging

logger = logging.getLogger(__name__)

def download_audio(link):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(settings.MEDIA_ROOT, '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': '/usr/bin/ffmpeg',
            'quiet': False,
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=True)
            audio_file = ydl.prepare_filename(info_dict).replace(".webm", ".mp3")
            if os.path.exists(audio_file):
                return audio_file
            else:
                logger.error("Failed to find the downloaded audio file.")
                return None

    except Exception as e:
        logger.error(f"Error downloading audio: {str(e)}")
        return None

import time
from requests.exceptions import RequestException

def get_transcription(link):
    max_retries = 5
    for attempt in range(max_retries):
        try:
            audio_file = download_audio(link)
            if not audio_file:
                logger.error("Failed to download the audio file.")
                return None

            transcriber = aai.Transcriber()
            transcript = transcriber.transcribe(audio_file)
            return transcript.text

        except RequestException as e:
            logger.error(f"Network error during transcription: {str(e)}")
            time.sleep(2 ** attempt)  # Exponential backoff

        except Exception as e:
            logger.error(f"Error during transcription: {str(e)}")
            return None





def generate_blog_from_transcription(transcription):
    try:
        prompt = f"Based on the following transcript from a YouTube video, write a comprehensive blog article. Ensure it reads like a proper blog article:\n\n{transcription}\n\nArticle:"

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )

        return response.choices[0].message['content'].strip()
    except openai.error.OpenAIError as e:
        logger.error(f"OpenAI API error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error generating blog content: {str(e)}")
        return None
    

def blog_list(request):
    blog_articles = BlogPost.objects.filter(user=request.user)
    return render(request, "all-blogs.html", {'blog_articles': blog_articles})

def blog_details(request, pk):
    try:
        blog_article_detail = BlogPost.objects.get(id=pk)
        if request.user == blog_article_detail.user:
            return render(request, 'blog-details.html', {'blog_article_detail': blog_article_detail})
        else:
            return redirect('/')
    except BlogPost.DoesNotExist:
        return redirect('/')

def user_login(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('/')
        else:
            error_message = "Invalid username or password"
            return render(request, 'login.html', {'error_message': error_message})
        
    return render(request, 'login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        repeatPassword = request.POST['repeatPassword']

        if password == repeatPassword:
            try:
                user = User.objects.create_user(username, email, password)
                user.full_clean()  # Validates the user model fields
                user.save()
                login(request, user)
                return redirect('/')
            except ValidationError as e:
                error_message = f"Error creating account: {e.message_dict}"
                return render(request, 'signup.html', {'error_message': error_message})
            except Exception as e:
                logger.error(f"Error during signup: {str(e)}")
                error_message = 'An error occurred while creating the account'
                return render(request, 'signup.html', {'error_message': error_message})
        else:
            error_message = 'Passwords do not match'
            return render(request, 'signup.html', {'error_message': error_message})
        
    return render(request, 'signup.html')

def user_logout(request):
    logout(request)
    return redirect('/')
