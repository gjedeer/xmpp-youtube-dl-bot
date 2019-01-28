#!/usr/bin/python
from __future__ import unicode_literals

"""
sudo apt install python-xmpp python-requests
"""

from xmpp import *
import datetime
import functools
import glob
import json
import mimetypes
import os.path
import re
import requests
import uuid

import youtube_dl
import youtube_dl.utils


import settings

http_upload_stanza_ids = {}
disco_step1_id = None

NS_HTTP_UPLOAD = 'urn:xmpp:http:upload'
MIN_PROGRESS_MESSAGE_SECONDS = 5

def send_text_message(sess, text, to=None):
    msg = protocol.Message(to, text, typ='chat')
    id = sess.send(msg)

def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)

class YTDLLogger(object):
    def __init__(self, message_cb, tick_cb):
	self.message_cb = message_cb
	self.tick_cb = tick_cb
	self.debug = self._send
	self.info = self._send
	self.warning = self._send
	self.error = self._send
	self.last_debug = datetime.datetime(1970, 1, 1)
        # output file name matched from ffmpeg log entry is saved here
        self.converted_file_name = None

    def _send(self, msg):
	self.tick_cb()

	msg = strip_ansi(msg).strip()

	if msg.startswith('[download]'):
	    now = datetime.datetime.now()
	    elapsed = now - self.last_debug
	    print "DOWNLOAD MSG", elapsed
	    if elapsed < datetime.timedelta(seconds=MIN_PROGRESS_MESSAGE_SECONDS):
		return
	    self.last_debug = now
	self.message_cb(text=strip_ansi(msg))
	self.tick_cb()
        converted_path_str = '[ffmpeg] Destination: '
        if msg.startswith(converted_path_str):
            self.converted_file_name = msg[len(converted_path_str):].strip()

def is_conversion_enabled():
    """
    A hacky way to find out if ffmpeg is ran after download
    """
    return settings.ydl_opts and 'postprocessors' in settings.ydl_opts and len(settings.ydl_opts['postprocessors']) > 0

def ytdl_progress_hook(sess, to, tick_cb, progress):
    print progress
    if progress['status'] == 'downloading':
	text = '%s of %s at %s - ETA %s' % (progress['_percent_str'], progress['_total_bytes_str'], progress['_speed_str'], progress['_eta_str'])
    elif progress['status'] == 'finished':
	text = 'Finished %s (%s)' % (progress['filename'], progress['_total_bytes_str'])
        if settings.send_after_download and not is_conversion_enabled():
            mime, enc = mimetypes.guess_type(progress['filename'])
            size_mb = '%.2f' % (os.path.getsize(progress['filename']) / (1024*1024.0))
            send_text_message(sess=sess,to=to, text='Uploading ' + logger.converted_file_name + '(' + size_mb + " MB)")
            start_upload(sess, to, {
                'filepath': os.path.join(settings.out_directory, progress['filename']),
                'content-type': mime,
                'delete': settings.delete_after_send,
            })
    else:
	text = json.dumps(progress)

#    message_cb(text=text)

def messageCB(sess, mess):
    print sess
    real_sess = sess._owner
    print real_sess
    body = mess.getBody()
    if not body:
	return

    fromjid, fromres = str(mess.getFrom()).split('/', 1)
    message_cb = functools.partial(send_text_message, sess=sess, to=fromjid)
    tick_cb = functools.partial(sess.Process, 0)
    logger = YTDLLogger(message_cb=message_cb, tick_cb=tick_cb)

    ydl_opts = {
	'logger': logger,
	'outtmpl': os.path.join(settings.out_directory, '%(title)s-%(id)s.%(ext)s'),
        'progress_hooks': [functools.partial(ytdl_progress_hook, real_sess, fromjid, tick_cb)],
    }
    if hasattr(settings, 'ydl_opts'):
        ydl_opts.update(settings.ydl_opts)

    try:
	with youtube_dl.YoutubeDL(ydl_opts) as ydl:
		ydl.download([body.strip()])
    except youtube_dl.utils.DownloadError:
	pass

    # Unfortunately, as of 2019-01-27, there is no progress callback from conversion,
    # so we have to fall back on a hack: capture converted file name from the logger
    # and send it when youtube_dl returns.
    if is_conversion_enabled() and logger.converted_file_name:
        mime, enc = mimetypes.guess_type(logger.converted_file_name)
        size_mb = '%.2f' % (os.path.getsize(logger.converted_file_name) / (1024*1024.0))
        message_cb(to=fromjid, text='Uploading ' + logger.converted_file_name + '(' + size_mb + " MB)")
        start_upload(real_sess, fromjid, {
            'filepath': os.path.join(settings.out_directory, logger.converted_file_name),
            'content-type': mime,
            'delete': settings.delete_after_send,
        })

    message_cb(to=fromjid, text='Finished processing: ' + body)

def send_url_message(sess, to, url):
    msg = protocol.Message(to, url, typ='chat')
    msg.setTag("x", {}, "jabber:x:oob")
    x_tag = msg.getTag("x", {}, "jabber:x:oob")
    x_tag.setTagData("url", url)
    id = sess.send(msg)

def iq_http_slot_cb(sess, stanza):
    id = stanza.getID()

    slot = stanza.getTag('slot', namespace=NS_HTTP_UPLOAD)
    print "SLOT:", slot

# TODO handle errors as in https://xmpp.org/extensions/xep-0363.html#errors
# TODO handle requests upload errors
    file_obj = http_upload_stanza_ids.get(id)
    del http_upload_stanza_ids[id]

    if slot:
	put_url = slot.getTagData('put')
	get_url = slot.getTagData('get')
	if put_url:
	    put = slot.getTag('put')
	    headers = {}
	    print "PUT slot:", put_url
	    header_tags = put.getTags('header')
	    for header_tag in header_tags:
		h_name = header_tag.getAttr('name')
		h_value = header_tag.getData()
		if h_name.lower() not in ('authorization', 'cookie', 'expires'):
		    continue
		headers[h_name] = h_value

	    r = requests.put(put_url, headers=headers, data=open(file_obj['filepath']))
	    if r.status_code <> 201:
		print "ERROR"
		print put
		print r.status_code
		print r.response_text
		return

	send_url_message(sess, file_obj['to'], get_url)
	if file_obj.get('delete', False):
	    os.unlink(file_obj['filepath'])

def iq_result_cb(sess, stanza):
    id = stanza.getID()
    print "Result ID:", id, "in http upload ids:", (id in http_upload_stanza_ids), "stanza", stanza
    if id in http_upload_stanza_ids:
	iq_http_slot_cb(sess, stanza)

    elif id == disco_step1_id or id is None:
	if stanza.getQueryNS() == 'http://jabber.org/protocol/disco#items':
	    print "== DISCO STEP1 received"
	    capabilities = stanza.getQueryChildren()
	    print capabilities
	

def iqCB(sess, stanza):
    typ = stanza.getType()
    print "== IQ callback, type %s" % typ
    if typ == 'result':
	iq_result_cb(sess, stanza)

def send_disco_step1_iq(cl):
    global disco_step1_id
    iq = protocol.Iq(typ='get', to=cl.Server)
    iq.setQueryNS('http://jabber.org/protocol/disco#items')

    disco_step1_id = cl.send(iq)

def start_upload(sess, to, file_obj):
    file_obj['filename'] = os.path.basename(file_obj['filepath'])
    file_obj['to'] = to
    domain = sess.Server
    iq = protocol.Iq(typ='get', to=domain)
    iq.setTag('request', namespace=NS_HTTP_UPLOAD)
    req = iq.getTag('request', namespace=NS_HTTP_UPLOAD)
    req.setTagData('filename', file_obj['filename'])
    req.setTagData('size', os.path.getsize(file_obj['filepath']))
    req.setTagData('content-type', file_obj.get('content-type', 'image/jpeg'))

    id = cl.send(iq)
    http_upload_stanza_ids[id] = file_obj
    print http_upload_stanza_ids

def ping(sess):
    iq = protocol.Iq(typ='get', to=domain)
    iq.setTag('ping', namespace='urn:xmpp:ping')
    id = sess.send(iq)

if __name__ == "__main__":
    domain = JID(settings.jid).getDomain()
    cl=Client(domain)
    cl.connect(proxy=settings.proxy)
    cl.RegisterHandler('message', messageCB)
    cl.RegisterHandler('iq', iqCB)
    cl.auth(JID(settings.jid).getNode(),settings.password)

    last_interaction = datetime.datetime.now()
    cl.Process(1)

    send_disco_step1_iq(cl)

    cl.sendInitPresence()
    pres = Presence()
    pres.setStatus('Send me an URL and I\'ll reply with an MP3')
    cl.send(pres)

    message_cb = functools.partial(send_text_message, sess=cl)

    while 1:
	cl.Process(.1)

	if datetime.datetime.now() - last_interaction > datetime.timedelta(minutes=1):
	    ping(cl)
	    last_interaction = datetime.datetime.now()
