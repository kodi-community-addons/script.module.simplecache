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
    mem_cache = {}
    exit = False
    auto_clean_interval = 4  # cleanup every 4 hours
    enable_win_cache = True
    enable_file_cache = True
    win = None
    busy_tasks = []

    def __init__(self, allow_mem_cache=False):
        '''Initialize our caching class'''
        self.win = xbmcgui.Window(10000)
        self.monitor = xbmc.Monitor()
        self.enable_mem_cache = allow_mem_cache
        self.check_cleanup()
        self.log_msg("Initialized")

    def close(self):
        '''tell background thread(s) to stop immediately and cleanup objects'''
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
        # 1: try memory cache first - only for objects that can be accessed by the same instance calling the addon!
        if self.enable_mem_cache and endpoint in self.mem_cache:
            cachedata = self.mem_cache[endpoint]
            if not checksum or checksum == cachedata["checksum"]:
                return cachedata["data"]

        # 2: try self.win property cache - usefull for plugins and scripts which dont run in the background
        cache_name = self.get_cache_name(endpoint)
        cache = self.win.getProperty(cache_name.encode("utf-8")).decode("utf-8")
        if self.enable_win_cache and cache:
            cachedata = eval(cache)
            if cachedata["expires"] > cur_time:
                if not checksum or checksum == cachedata["checksum"]:
                    return cachedata["data"]

        # 3: fallback to local file cache
        cachefile = self.get_cache_file(endpoint)
        if self.enable_file_cache and xbmcvfs.exists(cachefile):
            cachedata = self.read_cachefile(cachefile)
            if cachedata and cachedata["expires"] > cur_time:
                if not checksum or checksum == cachedata["checksum"]:
                    self.mem_cache[endpoint] = cachedata
                    return cachedata["data"]
        return None

    def set(self, endpoint, data, checksum="", expiration=datetime.timedelta(days=30), mem_cache=False):
        '''
            set an object in the cache
            endpoint: the (unique) name of the cache object as reference
            data: the data to store in the cache(can be any serializable python object)
            checkum: optional checksum to store in the cache
            expiration: set expiration of the object in the cache as timedelta
        '''
        thread.start_new_thread(self.set_internal, (endpoint, data, checksum, expiration, mem_cache))

    def set_internal(self, endpoint, data, checksum, expiration, mem_cache):
        '''
            internal method is called multithreaded so saving happens in the background
            and doesn't block the main code execution (as file writes can be file consuming)
        '''
        cache_name = self.get_cache_name(endpoint)
        cur_time = datetime.datetime.now()
        self.busy_tasks.append(cur_time)
        cachedata = {"date": cur_time, "endpoint": endpoint, "checksum": checksum, "data": data}
        memory_expiration = datetime.timedelta(hours=self.auto_clean_interval)

        cachedata["expires"] = cur_time + expiration

        # save in memory cache - only if allowed
        if self.enable_mem_cache and not self.exit:
            self.mem_cache[endpoint] = cachedata
        else:
            # window property cache as alternative for memory cache - usefull for (stateless) plugins
            # writes the data both in it's own self.win property and to a global list
            # the global list is used to determine which objects exist in memory cache
            cachedata_str = repr(cachedata).encode("utf-8")
            if self.enable_win_cache and not self.exit:
                all_win_cache_objects = self.win.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
                if all_win_cache_objects:
                    all_win_cache_objects = eval(all_win_cache_objects)
                else:
                    all_win_cache_objects = []
                all_win_cache_objects.append((cache_name))
                self.win.setProperty("script.module.simplecache.cacheobjects",
                                     repr(all_win_cache_objects).encode("utf-8"))
                self.win.setProperty(cache_name.encode("utf-8"), cachedata_str)

        # file cache only if cache persistance needs to be larger than memory cache expiration
        # dumps the data into a zlib compressed file on disk
        if self.enable_file_cache and expiration > memory_expiration and not not self.exit:
            cachedata["expires"] = cur_time + expiration
            cachedata_str = repr(cachedata).encode("utf-8")
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
        # always check if a cleanup is needed
        self.check_cleanup()

    def check_cleanup(self):
        '''check if cleanup is needed'''
        cur_time = datetime.datetime.now()
        lastexecuted = self.win.getProperty("simplecache.clean.lastexecuted")
        cleanup_interval = datetime.timedelta(hours=self.auto_clean_interval)
        if not lastexecuted:
            self.win.setProperty("simplecache.clean.lastexecuted", repr(cur_time))
        elif (eval(lastexecuted) + cleanup_interval) < cur_time:
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

        # cleanup memory cache objects
        self.mem_cache = {}

        # cleanup winprops cache objects
        all_win_cache_objects = self.win.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
        if all_win_cache_objects and not self.exit:
            cache_objects = []
            for item in eval(all_win_cache_objects):
                self.win.clearProperty(item.encode("utf-8"))
                if self.exit:
                    break
            # also clear our global list
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
