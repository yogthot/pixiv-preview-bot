#!/usr/bin/env python3

import os
import sys
import re
import tempfile
import json
import zipfile
import subprocess
import requests


class PixivDetails(os.PathLike):
    def __init__(self, path, filename, files=1):
        self.path = path
        self.filename = filename
        self.files = files
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        os.remove(self.path)
    
    def __fspath__(self):
        return self.path
    
    def __str__(self):
        return self.filename


class Pixiv:
    POST_REGEXP = re.compile('https?:\/\/(?:www\.)?pixiv\.net\/(?:[a-zA-Z]{2}\/)?artworks\/(?P<post_id>\d+)', flags=re.IGNORECASE)

    POST_GET_URL = 'https://www.pixiv.net/ajax/illust/{post_id}'
    #POST_PAGES_URL = 'https://www.pixiv.net/ajax/illust/{post_id}/pages'
    POST_UGOIRA_URL = 'https://www.pixiv.net/ajax/illust/{post_id}/ugoira_meta'
    
    def __init__(self, cookie):
        self.http = requests.Session()
        
        self.http.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:80.0) Gecko/20100101 Firefox/82.0',
            'Referer': 'https://www.pixiv.net/'
        })
        
        cookie = requests.cookies.create_cookie(name='PHPSESSID', value=cookie)
        self.http.cookies.set_cookie(cookie)
    
    def find_urls(self, text):
        return self.POST_REGEXP.findall(text)
    
    def _download(self, url):
        with self.http.get(url, stream=True) as resp:
            fd, path = tempfile.mkstemp()
            
            with os.fdopen(fd, 'w+b') as file:
                for chunk in resp.iter_content(chunk_size=8192):
                    file.write(chunk)
            
            return path
    
    def download_preview(self, post_id):
        response = self.http.get(self.POST_GET_URL.format(post_id=post_id))
        response.raise_for_status()
        post = json.loads(response.text)['body']
        
        if post['illustType'] == 2:
            # ugoira
            response = self.http.get(self.POST_UGOIRA_URL.format(post_id=post_id))
            response.raise_for_status()
            ugoira_meta = json.loads(response.text)['body']
            
            ugoira_zip = PixivFile(self._download(ugoira_meta['src']), None)
            frames = ugoira_meta['frames']
            
            fd, dst_path = tempfile.mkstemp()
            
            with ugoira_zip, \
                tempfile.TemporaryDirectory() as tmp_dir, \
                zipfile.ZipFile(ugoira_zip, 'r') as zip:
                
                zip.extractall(tmp_dir)
                
                inputs_path = f'{tmp_dir}/inputs.txt'
                with open(inputs_path, 'w+') as inputs:
                    for frame in frames:
                        inputs.write('file ' + str(frame['file']) + '\n')
                        inputs.write('duration ' + str(frame['delay'] / 1000) + '\n')
                
                arguments = [
                    'ffmpeg',
                    # input
                    '-f', 'concat',
                    '-i', str(inputs_path),
                    
                    # output
                    '-f', 'webm',
                    '-c:v', 'libvpx',
                    '-b:v', '10M',
                    '-an',
                    '-vsync', '2',
                    '-r', '1000',
                    '-y',
                    '-'
                ]
                
                FNULL = open(os.devnull, 'w')
                ffmpeg = subprocess.Popen(arguments, shell=False, stdin=FNULL, stdout=fd, stderr=subprocess.PIPE)
                out, err = ffmpeg.communicate()
                if ffmpeg.returncode:
                    if err: print(err.decode('utf-8'), file=sys.stderr)
            
            return PixivDetails(dst_path, f'{post_id}.webm')
            
            
        else:
            # get the first image and nothing else
            url = post['urls']['regular']
            files = post['pageCount']
            return PixivDetails(self._download(url), url.split('/')[-1], files)



