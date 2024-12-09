from config import *
from datetime import timedelta
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_session import Session
from minio import Minio
from minio.commonconfig import CopySource
from tld import get_tld, exceptions

import logging
import re
import uuid


## Configuration Details
# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Simple "email-like string" validation; supports "+" convention because I hate when stuff doesn't
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# Configure Minio client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=True
)

app = Flask(__name__)
app.secret_key = APP_SECRET

app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict'
)

## Utility Functions
def is_valid_email(email):
    if not EMAIL_REGEX.match(email):
        return False
    try:
        tld = get_tld(email, fix_protocol=True)
        return True
    except (exceptions.TldBadUrl, exceptions.TldDomainNotFound):
        return False

def sanitize_email_for_path(email):
    """Convert email to safe path format"""
    return email.replace('@', '_at_').replace('.', '_dot_')

def render_custom(template, **kwargs):
    context = {
        'page': template.capitalize(),
        'email': session.get('email', ''),
    }
    context.update(kwargs)
    return render_template(f'{template}.html', **context)

## Routes
# No explicit "index" page; we want email before we let the user do video things
@app.route('/')
def index():
    if 'email' not in session:
        return redirect(url_for('email_capture'))
    return render_custom('video')

@app.route('/email', methods=['GET', 'POST'])
def email_capture():
    if request.method == 'POST':
        email = request.form.get('email')

        if not is_valid_email(email):
            return render_custom('email', error='Invalid email address')

        session['email'] = email
        return redirect(url_for('index'))

    return render_custom('email')

@app.route('/video', methods=['POST'])
def video():
    if 'email' not in session:
        logger.error('No email in session')
        return jsonify({'error': 'Session expired'}), 401

    if 'video' not in request.files:
        logger.error('No video file in request')
        return jsonify({'error': 'No video file'}), 400

    video_file = request.files['video']

    # Check file size
    video_file.seek(0, 2)
    file_size = video_file.tell()
    video_file.seek(0)

    if file_size == 0:
        logger.error('Received empty file')
        return jsonify({'error': 'Empty file'}), 400

    logger.info(f'Uploading file of size: {file_size} bytes')

    video_id = str(uuid.uuid4())
    email_path = sanitize_email_for_path(session['email'])
    object_path = f"videos/{email_path}/{video_id}.webm"

    try:
        minio_client.put_object(
            MINIO_BUCKET,
            object_path,
            video_file,
            file_size,
            'video/webm'
        )
        logger.info(f'Successfully uploaded video {object_path}')

        return jsonify({'success': True, 'video_id': video_id})
    except Exception as e:
        logger.error(f'Upload failed: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/my-videos')
def my_videos():
    if 'email' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    email_path = sanitize_email_for_path(session['email'])
    videos = []

    try:
        # List objects in user's directory
        objects = minio_client.list_objects(MINIO_BUCKET, f"videos/{email_path}/")
        for obj in objects:
            logger.debug(f"Object: {obj.object_name}, Size: {obj.size}, Last Modified: {obj.last_modified}, Type: {type(obj.last_modified)}")
            if obj.object_name.endswith('.webm'):
                # Generate presigned URL for video access
                url = minio_client.presigned_get_object(
                    MINIO_BUCKET,
                    obj.object_name,
                    expires=timedelta(hours=1)
                )
                name = obj.object_name.split('/')[-1]

                logger.info(f"Name: {name}")
                logger.info(f"Presigned URL for {obj.object_name}: {url}")

                videos.append({
                    'name': name,
                    'url': url,
                    'date': obj.last_modified.isoformat() if hasattr(obj.last_modified, 'isoformat') else str(obj.last_modified)
                })
    except Exception as e:
        logger.error(f"Error listing videos: {str(e)}")
        return jsonify({'error': str(e)}), 500

    return jsonify(videos)

@app.route('/delete-video/<video_id>')
def delete_video(video_id):
    if 'email' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    email_path = sanitize_email_for_path(session['email'])
    source_path = f"videos/{email_path}/{video_id}"
    archive_path = f"archive/{email_path}/{video_id}"

    try:
        # Copy to archive
        copy_source = CopySource(MINIO_BUCKET, source_path)
        minio_client.copy_object(
            MINIO_BUCKET,
            archive_path,
            copy_source
        )
        # Delete original
        minio_client.remove_object(MINIO_BUCKET, source_path)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting video: {str(e)}")
        return jsonify({'error': str(e)}), 500

## Main
if __name__ == '__main__':
    app.run(debug=True)