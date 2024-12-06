from config import *
from flask import Flask, redirect, render_template, request, session, url_for
from flask_session import Session
from minio import Minio
from redis import Redis
from tld import get_tld, exceptions

import logging
import re


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
    return redirect(url_for('video'))

@app.route('/email', methods=['GET', 'POST'])
def email_capture():
    if request.method == 'POST':
        email = request.form.get('email')

        if not is_valid_email(email):
            return render_custom('email', error='Invalid email address')

        session['email'] = email
        return redirect(url_for('index'))

    return render_custom('email')

@app.route('/video')
def video():
    return render_custom('video')

# serve favicon.ico from the static directory
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')

# serve robots.txt from the static directory
@app.route('/robots.txt')
def robots_txt():
    return app.send_static_file('robots.txt')

## Main
if __name__ == '__main__':
    app.run(debug=True)