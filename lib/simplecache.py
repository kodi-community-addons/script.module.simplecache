# -*- coding: utf-8 -*-
import xbmcvfs, xbmcgui
import re, base64, zlib
import datetime
import unicodedata
import thread

WINDOW = xbmcgui.Window(10000)

use_memory_cache = True
use_file_cache = True
default_cache_path = "special://profile/addon_data/script.module.simplecache/"
default_mem_cache_expiration = datetime.timedelta(hours=2)

def get( endpoint, checksum=""):
    #get object from cache, always first try memory cache, than try filecache
    thread.start_new_thread(auto_cleanup, ())
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
    cachefile = getCacheFile(endpoint)
    if use_file_cache and xbmcvfs.exists(cachefile):
        data = read_cachefile(cachefile)
        if data and data["expires"] > n:
            if not checksum or checksum == data["checksum"]:
                return data["data"]

    return None

def set( endpoint, data, checksum="", expiration=datetime.timedelta(days=30)):
    #call internal method multithreaded so saving happens in the background
    thread.start_new_thread(set_internal, (endpoint,data,checksum,expiration))

def set_internal( endpoint, data, checksum="", expiration=datetime.timedelta(days=30)):
    #use window properties and local file as primitive cache
    #date is used to determine expiration
    auto_cleanup()
    cacheName = getCacheName(endpoint)
    n = datetime.datetime.now()
    expires = n + expiration
    cachedata = { "date": n, "expires":expires, "endpoint":endpoint, "data":data, "checksum":checksum }
    cachedata_str = repr(cachedata).encode("utf-8")

    #memory cache
    #writes the data both in it's own window property and to a global list
    #the global list is used to determine when objects should be deleted from the memory cache
    if use_memory_cache:
        allCacheObjects = WINDOW.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
        if allCacheObjects: allCacheObjects = eval(allCacheObjects)
        else: allCacheObjects = []
        if expiration < default_mem_cache_expiration:
            mem_expires = n + expires
        else: mem_expires = n + default_mem_cache_expiration
        allCacheObjects.append( (cacheName, mem_expires) )
        WINDOW.setProperty("script.module.simplecache.cacheobjects",repr(allCacheObjects).encode("utf-8"))
        #set data in cache
        WINDOW.setProperty(cacheName.encode("utf-8"), cachedata_str)

    #file cache only if cache persistance needs to be larger than memory cache expiration
    #dumps the data into a zlib compressed file on disk
    if use_file_cache and expiration > default_mem_cache_expiration:
        if not xbmcvfs.exists(default_cache_path):
            xbmcvfs.mkdirs(default_cache_path)

        cachefile = getCacheFile(endpoint)
        f = xbmcvfs.File(cachefile.encode("utf-8"), 'w')
        cachedata = zlib.compress(cachedata_str)
        f.write(cachedata)
        f.close()

def getCacheName( endpoint ):
    value = base64.encodestring(try_encode(endpoint)).decode("utf-8")
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip().lower())
    value = unicode(re.sub('[-\s]+', '-', value))
    return value

def getCacheFile( endpoint ):
    return default_cache_path + getCacheName(endpoint)

def auto_cleanup():
    #auto cleanup to remove any lingering cache objects
    n = datetime.datetime.now()
    lastexecuted = WINDOW.getProperty("script.module.simplecache.clean.lastexecuted")
    if not lastexecuted:
        #skip cleanup on first run
        WINDOW.setProperty("script.module.simplecache.clean.lastexecuted",repr(n))
    else:
        lastexecuted = eval(lastexecuted)
        #cleanup old cache entries, based on expiration key
        if (lastexecuted + default_mem_cache_expiration) < n:

            WINDOW.setProperty("script.module.simplecache.clean.lastexecuted",repr(n))

            #cleanup memory cache objects (window properties)
            allCacheObjects = WINDOW.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
            if allCacheObjects:
                cacheObjects = []
                for item in eval(allCacheObjects):
                    if item[1] <= n:
                        WINDOW.clearProperty(item[0].encode("utf-8"))
                    else:
                        cacheObjects.append(item)
                #Store our list with cacheobjects again
                WINDOW.setProperty("script.module.simplecache.cacheobjects",repr(cacheObjects).encode("utf-8"))

            #cleanup file cache objects
            if xbmcvfs.exists(default_cache_path):
                dirs, files = xbmcvfs.listdir(default_cache_path)
                n = datetime.datetime.now()
                for file in files:

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
                    except Exception:
                        #delete any corrupted files
                        xbmcvfs.delete(cachefile)

def read_cachefile(cachefile):
    try:
        f = xbmcvfs.File(cachefile.encode("utf-8"), 'r')
        text =  f.read()
        f.close()
        text = zlib.decompress(text).decode("utf-8")
        data = eval(text)
        return data
    except Exception:
        return {}

def try_encode(text, encoding="utf-8"):
    try:
        return text.encode(encoding,"ignore")
    except Exception:
        return text

def try_decode(text, encoding="utf-8"):
    try:
        return text.decode(encoding,"ignore")
    except Exception:
        return text
