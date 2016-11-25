#!/usr/bin/python
# -*- coding: utf-8 -*-

'''provides a simple stateless caching system for Kodi addons and plugins'''

import xbmcvfs
import xbmcgui
import xbmc
import re
import base64
import zlib
import datetime
import unicodedata
import threading
import thread

DEFAULTCACHEPATH = "special://profile/addon_data/script.module.simplecache/"


class SimpleCache(object):
    '''simple stateless caching system for Kodi'''
    exit = False
    auto_clean_interval = datetime.timedelta(hours=4)
    enable_win_cache = True
    enable_file_cache = True
    win = None
    busy_tasks = []

    def __init__(self):
        '''Initialize our caching class'''
        self.win = xbmcgui.Window(10000)
        self.monitor = xbmc.Monitor()
        all_win_cache_objects = self.win.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
        if all_win_cache_objects:
            self.all_win_cache_objects = eval(all_win_cache_objects)
        else:
            self.all_win_cache_objects = []
        self.check_cleanup()
        self.log_msg("Initialized")

    def close(self):
        '''tell any tasks to stop immediately (as we can be called multithreaded) and cleanup objects'''
        if self.win:
            self.win.setProperty("script.module.simplecache.cacheobjects",
                repr(self.all_win_cache_objects).encode("utf-8"))
        self.exit = True
        # wait for all tasks to complete
        while self.busy_tasks:
            xbmc.sleep(25)
        self.win = None
        self.monitor = None
        del self.win
        del self.monitor
        self.log_msg("Closed")
        
    def __del__(self):
        '''make sure close is called'''
        if not self.exit:
            self.close()

    def get(self, endpoint, checksum=""):
        '''
            get object from cache and return the results
            endpoint: the (unique) name of the cache object as reference
            checkum: optional argument to check if the cacheobjects matches the checkum
        '''
        cur_time = datetime.datetime.now()
        cache_name = self.get_cache_name(endpoint)

        # 1: try window property cache - usefull for plugins and scripts which dont run in the background
        cache = self.win.getProperty(cache_name.encode("utf-8")).decode("utf-8")
        if self.enable_win_cache and cache:
            cachedata = eval(cache)
            if cachedata["expires"] > cur_time:
                if not checksum or checksum == cachedata["checksum"]:
                    return cachedata["data"]

        # 2: fallback to local file cache
        cachefile = self.get_cache_file(endpoint)
        if self.enable_file_cache and xbmcvfs.exists(cachefile):
            cachedata = self.read_cachefile(cachefile)
            if cachedata and cachedata["expires"] > cur_time:
                if not checksum or checksum == cachedata["checksum"]:
                    self.set_win_cache(cache_name, repr(cachedata))
                    return cachedata["data"]
        return None

    def set(self, endpoint, data, checksum="", expiration=datetime.timedelta(days=30)):
        '''
            set data in cache
        '''
        cache_name = self.get_cache_name(endpoint)
        cur_time = datetime.datetime.now()
        self.busy_tasks.append(cur_time)
        cachedata = {
            "date": cur_time, 
            "endpoint": endpoint, 
            "checksum": checksum,
            "expires": cur_time + expiration,
            "data": data}
        
        cachedata_str = repr(cachedata).encode("utf-8")

        # memory cache: write to window property
        if self.enable_win_cache and not self.exit:
            self.set_win_cache(cache_name, cachedata_str)

        # file cache only if cache persistance needs to be larger than memory cache expiration
        # dumps the data into a zlib compressed file on disk
        if self.enable_file_cache and expiration > self.auto_clean_interval and not self.exit:
            cachedata["expires"] = cur_time + expiration
            if not xbmcvfs.exists(DEFAULTCACHEPATH):
                xbmcvfs.mkdirs(DEFAULTCACHEPATH)
            cachefile = self.get_cache_file(endpoint)
            _file = xbmcvfs.File(cachefile.encode("utf-8"), 'w')
            cachedata = zlib.compress(cachedata_str)
            _file.write(cachedata)
            _file.close()
            del _file
            
        # remove this task from list
        self.busy_tasks.remove(cur_time)

    def set_win_cache(self, cache_name, cachedata_str):
        '''
            window property cache as alternative for memory cache - usefull for (stateless) plugins
            writes the data both in it's own self.win property and to a global list
            the global list is used to determine which objects exist in memory cache
        '''
        self.all_win_cache_objects.append((cache_name))
        self.win.setProperty(cache_name.encode("utf-8"), cachedata_str)
    
    def check_cleanup(self):
        '''check if cleanup is needed'''
        cur_time = datetime.datetime.now()
        lastexecuted = self.win.getProperty("simplecache.clean.lastexecuted")
        if not lastexecuted:
            self.win.setProperty("simplecache.clean.lastexecuted", repr(cur_time))
        elif (eval(lastexecuted) + self.auto_clean_interval) < cur_time:
            # cleanup needed...
            self.do_cleanup()

    def do_cleanup(self):
        '''perform cleanup task'''
        if self.exit:
            return
        cur_time = datetime.datetime.now()
        self.busy_tasks.append(cur_time)
        self.win.setProperty("simplecache.clean.lastexecuted", repr(cur_time))
        self.log_msg("Running cleanup...", xbmc.LOGNOTICE)

        # cleanup winprops cache objects
        for item in self.all_win_cache_objects:
            self.win.clearProperty(item.encode("utf-8"))
            if self.exit:
                break
        # also clear our global list
        self.all_win_cache_objects = []
        self.win.clearProperty("script.module.simplecache.cacheobjects")

        # cleanup file cache objects
        if xbmcvfs.exists(DEFAULTCACHEPATH) and not self.exit:
            files = xbmcvfs.listdir(DEFAULTCACHEPATH)[1]
            for file in files:
                # check filebased cache for expired items
                if self.exit:
                    break
                cachefile = DEFAULTCACHEPATH + file
                _file = xbmcvfs.File(cachefile, 'r')
                text = _file.read()
                _file.close()
                del _file
                try:
                    text = zlib.decompress(text).decode("utf-8")
                    data = eval(text)
                    if data["expires"] < cur_time:
                        xbmcvfs.delete(cachefile)
                except Exception as exc:
                    # delete any corrupted files
                    self.log_msg("Error in cleanup: %s" %repr(log_msg), xbmc.LOGWARNING)
                    xbmcvfs.delete(cachefile)
        self.log_msg("Auto cleanup done", xbmc.LOGNOTICE)
        # remove task from list
        self.busy_tasks.remove(cur_time)

    @staticmethod
    def read_cachefile(cachefile):
        '''try to read a file on disk and return the cache data'''
        try:
            _file = xbmcvfs.File(cachefile.encode("utf-8"), 'r')
            text = _file.read()
            _file.close()
            del _file
            text = zlib.decompress(text).decode("utf-8")
            data = eval(text)
            return data
        except Exception:
            return {}

    def get_cache_name(self, endpoint):
        '''helper to get our base64 representation of the cache identifier'''
        value = base64.encodestring(self.try_encode(endpoint)).decode("utf-8")
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
        value = unicode(re.sub('[^\w\s-]', '', value).strip().lower())
        value = unicode(re.sub('[-\s]+', '-', value))
        return value

    def get_cache_file(self, endpoint):
        '''helper to return the filename of the cachefile'''
        return DEFAULTCACHEPATH + self.get_cache_name(endpoint)

    @staticmethod
    def try_encode(text, encoding="utf-8"):
        '''helper to encode a string'''
        try:
            return text.encode(encoding, "ignore")
        except Exception:
            return text

    @staticmethod
    def log_msg(msg, loglevel=xbmc.LOGDEBUG):
        '''helper to send a message to the kodi log'''
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        xbmc.log("Skin Helper Simplecache --> %s" % msg, level=loglevel)


def use_cache(cache_days=14):
    '''
        wrapper around our simple cache to use as decorator
        Usage: define an instance of SimpleCache with name "cache" (self.cache) in your class
        Any method that needs caching just add @use_cache as decorator
        NOTE: use unnamed arguments for calling the method and named arguments for optional settings
    '''
    def decorator(func):
        '''our decorator'''
        def decorated(*args, **kwargs):
            '''process the original method and apply caching of the results'''
            method_class = args[0]
            method_class_name = method_class.__class__.__name__
            cache_str = "%s.%s" % (method_class_name, func.__name__)
            # cache identifier is based on positional args only
            # named args are considered optional and ignored
            for item in args[1:]:
                cache_str += u".%s" % item
            cache_str = cache_str.lower()
            cachedata = method_class.cache.get(cache_str)
            global_cache_ignore = False
            try:
                global_cache_ignore = method_class.ignore_cache
            except Exception:
                pass
            if cachedata is not None and not kwargs.get("ignore_cache", False) and not global_cache_ignore:
                return cachedata
            else:
                result = func(*args, **kwargs)
                method_class.cache.set(cache_str, result, expiration=datetime.timedelta(days=cache_days))
                return result
        return decorated
    return decorator
