import os
import hashlib

def create_folder(path):
    os.makedirs(path, exist_ok=True)

def hash_url(url):
    return hashlib.md5(url.encode()).hexdigest()