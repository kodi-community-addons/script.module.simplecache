# -*- coding: utf-8 -*-
import xbmc, xbmcvfs, xbmcgui
import re, base64, zlib
import datetime
import unicodedata

WINDOW = xbmcgui.Window(10000)

use_memory_cache = True
use_file_cache = True
default_cache_path = "special://profile/addon_data/script.module.simplecache/"
    
def get( endpoint, checksum=""):
    #get object from cache, always first try memory cache, than try filecache
    auto_cleanup()    
    cacheName = getCacheName(endpoint)
    n = datetime.datetime.now()
    
    #try memory cache first
    cache = WINDOW.getProperty(cacheName.encode("utf-8")).decode("utf-8")
    if use_memory_cache and cache:
        data = eval(cache)
        if data["expires"] > n:
            if not checksum or checksum == data["checksum"]:
                return data["data"]

    #fallback to local file cache
    cachefile = default_cache_path + cacheName
    if use_file_cache and xbmcvfs.exists(cachefile):
        try:
            f = xbmcvfs.File(cachefile.encode("utf-8"), 'r')
            text =  f.read()
            f.close()
            text = zlib.decompress(text).decode("utf-8")
            data = eval(text)
            if data["expires"] > n:
                if not checksum or checksum == data["checksum"]:
                    return data["data"]
        except KeyError: 
            pass #ignore any corrupted files
            
    return None
    
def set( endpoint, data, checksum="", expiration=datetime.timedelta(days=30)):
    #use window properties and local file as primitive cache
    #date is used to determine expiration
    auto_cleanup()
    cacheName = getCacheName(endpoint)
    n = datetime.datetime.now()
    expires = n + expiration
    cachedata = { "date": n, "expires":expires, "endpoint":endpoint, "data":data, "checksum":checksum }
    cachedata_str = repr(cachedata).encode("utf-8")
    
    #memory cache
    if use_memory_cache:
        WINDOW.setProperty(cacheName.encode("utf-8"), cachedata_str)
    
    #file cache
    if use_file_cache:
        if not xbmcvfs.exists(default_cache_path):
            xbmcvfs.mkdirs(default_cache_path)
            
        cachefile = cachefile = default_cache_path + cacheName
        f = xbmcvfs.File(cachefile.encode("utf-8"), 'w')
        cachedata = zlib.compress(cachedata_str)
        text =  f.write(cachedata)
        f.close()
                   
def getCacheName( endpoint ):
    value = base64.encodestring(endpoint).decode("utf-8")
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip().lower())
    value = unicode(re.sub('[-\s]+', '-', value))
    return value
    
def auto_cleanup():
    #auto cleanup to remove any lingering cache objects
    #runs every 2 hours
    n = datetime.datetime.now()
    lastexecuted = WINDOW.getProperty("script.module.simplecache.clean.lastexecuted")
    if not lastexecuted:
        #skip cleanup on first run
        WINDOW.setProperty("script.module.simplecache.clean.lastexecuted",repr(n))
    else:
        lastexecuted = eval(lastexecuted)
        if (lastexecuted + datetime.timedelta(hours=2)) < n:
            #cleanup old cache entries, based on expiration key
            WINDOW.setProperty("script.module.simplecache.clean.lastexecuted",repr(n))
            if xbmcvfs.exists(default_cache_path):
                dirs, files = xbmcvfs.listdir(default_cache_path)
                n = datetime.datetime.now()
                for file in files:
                
                    #memory cache always expires at every interval to prevent useless chunks of data stored in memory
                    cache = WINDOW.clearProperty(file.encode("utf-8"))
                    
                    #check filebased cache for expired items
                    cachefile = default_cache_path + file
                    try:
                        f = xbmcvfs.File(cachefile, 'r')
                        text =  f.read()
                        f.close()
                        text = zlib.decompress(text).decode("utf-8")
                        data = eval(text)
                        if data["expires"] < n:
                            xbmcvfs.delete(cachefile)
                    except:
                        #delete any corrupted files
                        xbmcvfs.delete(cachefile)
            
