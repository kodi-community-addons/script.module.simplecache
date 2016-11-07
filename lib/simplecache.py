# -*- coding: utf-8 -*-
import xbmcvfs, xbmcgui, xbmc
import re, base64, zlib
import datetime
import unicodedata
import threading, thread
import atexit

DEFAULTCACHEPATH = "special://profile/addon_data/script.module.simplecache/"

class SimpleCache(object):
    '''simple stateless caching system for Kodi'''
    mem_cache = {}
    exit = False
    auto_clean_interval = 3600 #cleanup every 60 minutes (3600 seconds)
    enable_win_cache = True
    enable_file_cache = True
    win = None
    busy_tasks = []

    def __init__(self, autocleanup=False):
        '''Initialize our caching class'''
        self.win = xbmcgui.Window(10000)
        self.monitor = xbmc.Monitor()
        if autocleanup:
            thread = threading.Thread(target=self.auto_cleanup, args=())
            thread.daemon = True
            thread.start()
        else:
            self.manual_cleanup()
        self.log_msg("Initialized")

    def close(self):
        '''tell background thread(s) to stop immediately and cleanup objects'''
        self.exit = True
        #wait for all tasks to complete
        xbmc.sleep(25)
        while self.busy_tasks:
            xbmc.sleep(25)
        del self.win
        del self.monitor
        self.log_msg("Exited")

    def get( self, endpoint, checksum=""):
        '''
            get object from cache and return the results
            endpoint: the (unique) name of the cache object as reference
            checkum: optional argument to check if the cacheobjects matches the checkum
        '''
        cur_time = datetime.datetime.now()
        #1: try memory cache first - only for objects that can be accessed by the same instance calling the addon!
        if endpoint in self.mem_cache:
            cachedata = self.mem_cache[endpoint]
            if not checksum or checksum == cachedata["checksum"]:
                return cachedata["data"]

        #2: try self.win property cache - usefull for plugins and scripts which dont run in the background
        cache_name = self.get_cache_name(endpoint)
        cache = self.win.getProperty(cache_name.encode("utf-8")).decode("utf-8")
        if self.enable_win_cache and cache:
            cachedata = eval(cache)
            if cachedata["expires"] > cur_time:
                if not checksum or checksum == cachedata["checksum"]:
                    return cachedata["data"]

        #3: fallback to local file cache
        cachefile = self.get_cache_file(endpoint)
        if self.enable_file_cache and xbmcvfs.exists(cachefile):
            cachedata = self.read_cachefile(cachefile)
            if cachedata and cachedata["expires"] > cur_time:
                if not checksum or checksum == cachedata["checksum"]:
                    return cachedata["data"]

        return None

    def set( self, endpoint, data, checksum="", expiration=datetime.timedelta(days=30), mem_cache=False):
        '''
            set an object in the cache
            endpoint: the (unique) name of the cache object as reference
            data: the data to store in the cache(can be any serializable python object)
            checkum: optional checksum to store in the cache
            expiration: set expiration of the object in the cache as timedelta
            mem_cache: optional bool - store in memory instead of window props - practical if used within same instance
        '''
        thread.start_new_thread(self.set_internal, (endpoint,data,checksum,expiration,mem_cache))

    def set_internal( self, endpoint, data, checksum, expiration, mem_cache):
        '''
            internal method is called multithreaded so saving happens in the background
            and doesn't block the main code execution (as file writes can be file consuming)
        '''
        cache_name = self.get_cache_name(endpoint)
        cur_time = datetime.datetime.now()
        self.busy_tasks.append(cur_time)
        cachedata = { "date": cur_time, "endpoint":endpoint, "checksum":checksum, "data": data }
        memory_expiration = datetime.timedelta(minutes=self.auto_clean_interval)

        if expiration < memory_expiration:
            mem_expires = cur_time + expiration
        else:
            mem_expires = cur_time + memory_expiration
        cachedata["expires"] = mem_expires

        #save in memory cache - only if allowed
        if mem_cache:
            self.mem_cache[endpoint] = cachedata
        else:
            #window property cache
            #writes the data both in it's own self.win property and to a global list
            #the global list is used to determine when objects should be deleted from the memory cache
            cachedata_str = repr(cachedata).encode("utf-8")
            if self.enable_win_cache:
                all_win_cache_objects = self.win.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
                if all_win_cache_objects:
                    all_win_cache_objects = eval(all_win_cache_objects)
                else:
                    all_win_cache_objects = []
                all_win_cache_objects.append( (cache_name, mem_expires) )
                self.win.setProperty("script.module.simplecache.cacheobjects",
                    repr(all_win_cache_objects).encode("utf-8"))
                self.win.setProperty(cache_name.encode("utf-8"), cachedata_str)
            
        #file cache only if cache persistance needs to be larger than memory cache expiration
        #dumps the data into a zlib compressed file on disk
        if self.enable_file_cache and expiration > memory_expiration:
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
        #remove task from list
        self.busy_tasks.remove(cur_time)

    def auto_cleanup(self):
        '''auto cleanup to remove any expired cache objects - usefull for services'''
        self.log_msg("Auto cleanup backgroundworker started...")
        self.busy_tasks.append("auto_cleanup")
        cur_tick = 0
        while not (self.exit or self.monitor.abortRequested()):
            if cur_tick == self.auto_clean_interval:
                cur_tick = 0
                self.do_cleanup()
            else:
                cur_tick += 5
            self.monitor.waitForAbort(5)
        self.busy_tasks.remove("auto_cleanup")
        self.log_msg("Auto cleanup backgroundworker stopped...")

    def manual_cleanup(self):
        '''manual cleanup to start only at initialization if autoclean worker is disabled - usefull for plugins'''
        cur_time = datetime.datetime.now()
        lastexecuted = self.win.getProperty("simplecache.clean.lastexecuted")
        memory_expiration = datetime.timedelta(seconds=self.auto_clean_interval)
        if not lastexecuted:
            self.win.setProperty("simplecache.clean.lastexecuted",repr(cur_time))
        elif (eval(lastexecuted) + memory_expiration) < cur_time:
            #cleanup needed...
            self.do_cleanup()

    def do_cleanup(self):
        '''perform cleanup task'''
        if self.exit:
            return
        cur_time = datetime.datetime.now()
        self.busy_tasks.append(cur_time)
        self.win.setProperty("simplecache.clean.lastexecuted",repr(cur_time))
        self.log_msg("Running cleanup...", xbmc.LOGNOTICE)

        #cleanup memory cache objects
        keys_to_delete = []
        for key, value in self.mem_cache.iteritems():
            if value["expires"] < cur_time:
                keys_to_delete.append(key)
        temp_dict = dict(self.mem_cache)
        for key in keys_to_delete:
            del temp_dict[key]
        self.mem_cache = temp_dict

        #cleanup winprops cache objects
        all_win_cache_objects = self.win.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
        if all_win_cache_objects:
            cacheObjects = []
            for item in eval(all_win_cache_objects):
                if item[1] <= cur_time:
                    self.win.clearProperty(item[0].encode("utf-8"))
                else:
                    cacheObjects.append(item)
                if self.monitor.abortRequested():
                    return
            #Store our list with cacheobjects again
            self.win.setProperty("script.module.simplecache.cacheobjects",repr(cacheObjects).encode("utf-8"))

        #cleanup file cache objects
        if xbmcvfs.exists(DEFAULTCACHEPATH):
            files = xbmcvfs.listdir(DEFAULTCACHEPATH)[1]
            for file in files:
                #check filebased cache for expired items
                if self.monitor.abortRequested():
                    return
                cachefile = DEFAULTCACHEPATH + file
                f = xbmcvfs.File(cachefile, 'r')
                text =  f.read()
                f.close()
                del f
                try:
                    text = zlib.decompress(text).decode("utf-8")
                    data = eval(text)
                    if data["expires"] < cur_time:
                        xbmcvfs.delete(cachefile)
                except Exception:
                    #delete any corrupted files
                    xbmcvfs.delete(cachefile)
        self.log_msg("Auto cleanup done",xbmc.LOGNOTICE)
        #remove task from list
        self.busy_tasks.remove(cur_time)

    @staticmethod
    def read_cachefile(cachefile):
        '''try to read a file on disk and return the cache data'''
        try:
            f = xbmcvfs.File(cachefile.encode("utf-8"), 'r')
            text =  f.read()
            f.close()
            del f
            text = zlib.decompress(text).decode("utf-8")
            data = eval(text)
            return data
        except Exception:
            return {}

    def get_cache_name( self, endpoint ):
        '''helper to get our base64 representation of the cache identifier'''
        value = base64.encodestring(self.try_encode(endpoint)).decode("utf-8")
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
        value = unicode(re.sub('[^\w\s-]', '', value).strip().lower())
        value = unicode(re.sub('[-\s]+', '-', value))
        return value

    def get_cache_file( self, endpoint ):
        '''helper to return the filename of the cachefile'''
        return DEFAULTCACHEPATH + self.get_cache_name(endpoint)

    ###### Utilities ##############################
    @staticmethod
    def try_encode(text, encoding="utf-8"):
        '''helper to encode a string'''
        try:
            return text.encode(encoding,"ignore")
        except Exception:
            return text

    @staticmethod
    def log_msg(msg, loglevel = xbmc.LOGDEBUG):
        '''helper to send a message to the kodi log'''
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        xbmc.log("Skin Helper Simplecache --> %s" %msg, level=loglevel)

#decorator to use cache on classmethods
def use_cache(cache_days=14, mem_cache=False):
    '''
        wrapper around our simple cache to use as decorator
        Usage: define an instance of SimpleCache with name "cache" (self.cache) in your class
        Any method that needs caching just add @use_cache as decorator
        NOTE: use unnamed arguments for calling the method and named arguments for optional settings
    '''
    def decorator(func):
        def decorated( *args, **kwargs):
            method_class = args[0]
            method_class_name = method_class.__class__.__name__
            cache_str = "%s.%s" %(method_class_name, func.__name__)
            # cache identifier is based on positional args only
            # named args are considered optional and ignored
            for item in args[1:]:
                cache_str += u".%s" %item
            cache_str = cache_str.lower()
            cachedata = method_class.cache.get(cache_str)
            global_cache_ignore = False
            try:
                global_cache_ignore = method_class.ignore_cache
            except Exception:
                pass
            if cachedata != None and not kwargs.get("ignore_cache",False) and not global_cache_ignore:
                return cachedata
            else:
                result = func( *args, **kwargs)
                method_class.cache.set(cache_str, result, expiration=datetime.timedelta(days=cache_days),
                    mem_cache=mem_cache)
                return result
        return decorated
    return decorator
