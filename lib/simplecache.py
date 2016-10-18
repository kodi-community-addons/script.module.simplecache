# -*- coding: utf-8 -*-
import xbmcvfs, xbmcgui, xbmc
import re, base64, zlib
import datetime
import unicodedata
import thread
import inspect
from functools import wraps


DEFAULTCACHEPATH = "special://profile/addon_data/script.module.simplecache/"
DEF_MEM_EXPIRATION = datetime.timedelta(hours=2)

def use_cache(cache_days=14):
    '''wrapper around our simple cache to use as decorator'''
    def decorator(func):
        def decorated( *args, **kwargs):
            self = args[0]
            cache_str = "%s.%s" %(self.__class__.__name__, func.__name__)
            for item in args:
                if not item == self:
                    cache_str += ".%s" %item
            for item in kwargs.itervalues():
                cache_str += ".%s" %item
            cachedata = self.cache.get(cache_str)
            if kwargs.get("ignore_cache",False):
                cachedata = None
            if cachedata:
                return cachedata
            else:
                result = func( *args, **kwargs)
                if not result:
                    result = {"no result":"no results"}
                self.cache.set(cache_str,result,expiration=datetime.timedelta(days=cache_days))
                return result
        return decorated
    return decorator
  

class SimpleCache(object):
    '''simple stateless caching system for Kodi'''
    mem_cache = {}
    enable_win_cache = True
    enable_file_cache = True
    
    def __init__(self, *args):
        #run automated cleanup task on startup
        self.win = xbmcgui.Window(10000)
        thread.start_new_thread(self.auto_cleanup, ())
        log_msg("Initialized")
        
    
    def get( self, endpoint, checksum=""):
        '''
            get object from cache and return the results
            endpoint: the (unique) name of the cache object as reference
            checkum: optional argument to check if the cacheobjects matches the checkum
        '''
        n = datetime.datetime.now()
        #1: try memory cache first
        if endpoint in self.mem_cache:
            cachedata = self.mem_cache[endpoint]
            if not checksum or checksum == cachedata["checksum"]:
                return cachedata["data"]
                
        #2: try self.win property cache - usefull for plugins and scripts which dont run in the background
        cache_name = self.get_cache_name(endpoint)
        cache = self.win.getProperty(cache_name.encode("utf-8")).decode("utf-8")
        if self.enable_win_cache and cache:
            cachedata = eval(cache)
            if cachedata["expires"] > n:
                if not checksum or checksum == cachedata["checksum"]:
                    return cachedata["data"]
                    
        #3: fallback to local file cache
        cachefile = self.get_cache_file(endpoint)
        if self.enable_file_cache and xbmcvfs.exists(cachefile):
            cachedata = self.read_cachefile(cachefile)
            if cachedata and cachedata["expires"] > n:
                if not checksum or checksum == cachedata["checksum"]:
                    return cachedata["data"]

        return None

    def set( self, endpoint, data, checksum="", expiration=datetime.timedelta(days=30)):
        '''
            set an object in the cache
            endpoint: the (unique) name of the cache object as reference
            data: the data to store in the cache(can be any serializable python object)
            checkum: optional checksum to store in the cache
            expiration: set expiration of the object in the cache as timedelta
        '''
        thread.start_new_thread(self.set_internal, (endpoint,data,checksum,expiration))

    def set_internal( self, endpoint, data, checksum, expiration):
        '''
            internal method is called multithreaded so saving happens in the background
            and doesn't block the main code execution (as file writes can be file consuming)
        '''
        cache_name = self.get_cache_name(endpoint)
        n = datetime.datetime.now()
        expires = n + expiration
        cachedata = { "date": n, "expires":expires, "endpoint":endpoint, "data":data, "checksum":checksum }
        cachedata_str = repr(cachedata).encode("utf-8")
        
        #save in memory cache
        self.mem_cache[endpoint] = cachedata

        #self.win property cache
        #writes the data both in it's own self.win property and to a global list
        #the global list is used to determine when objects should be deleted from the memory cache
        if self.enable_win_cache:
            all_win_cache_objects = self.win.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
            if all_win_cache_objects: 
                all_win_cache_objects = eval(all_win_cache_objects)
            else: 
                all_win_cache_objects = []
            if expiration < DEF_MEM_EXPIRATION:
                mem_expires = n + expires
            else: 
                mem_expires = n + DEF_MEM_EXPIRATION
            all_win_cache_objects.append( (cache_name, mem_expires) )
            self.win.setProperty("script.module.simplecache.cacheobjects",repr(all_win_cache_objects).encode("utf-8"))
            #set data in cache
            self.win.setProperty(cache_name.encode("utf-8"), cachedata_str)

        #file cache only if cache persistance needs to be larger than memory cache expiration
        #dumps the data into a zlib compressed file on disk
        if self.enable_file_cache and expiration > DEF_MEM_EXPIRATION:
            if not xbmcvfs.exists(DEFAULTCACHEPATH):
                xbmcvfs.mkdirs(DEFAULTCACHEPATH)

            cachefile = self.get_cache_file(endpoint)
            f = xbmcvfs.File(cachefile.encode("utf-8"), 'w')
            cachedata = zlib.compress(cachedata_str)
            f.write(cachedata)
            f.close()

    def auto_cleanup(self):
        '''auto cleanup to remove any lingering cache objects'''
        n = datetime.datetime.now()
        lastexecuted = self.win.getProperty("simplecache.clean.lastexecuted")
        if not lastexecuted:
            #skip cleanup on first run
            self.win.setProperty("simplecache.clean.lastexecuted",repr(n))
        else:
            lastexecuted = eval(lastexecuted)
            #cleanup old cache entries, based on expiration key
            if (lastexecuted + DEF_MEM_EXPIRATION) < n:
                log_msg("Run auto cleanup")
                self.win.setProperty("simplecache.clean.lastexecuted",repr(n))
                
                #cleanup memory cache objects
                keys_to_delete = []
                for key, value in self.mem_cache.iteritems():
                    if value["expires"] < n:
                        keys_to_delete.append(key)
                temp_dict = dict(self.mem_cache)
                for key in keys_to_delete:
                    del temp_dict[key]
                self.mem_cache = temp_dict
                
                #cleanup self.winprops cache objects
                all_win_cache_objects = self.win.getProperty("script.module.simplecache.cacheobjects").decode("utf-8")
                if all_win_cache_objects:
                    cacheObjects = []
                    for item in eval(all_win_cache_objects):
                        if item[1] <= n:
                            self.win.clearProperty(item[0].encode("utf-8"))
                        else:
                            cacheObjects.append(item)
                    #Store our list with cacheobjects again
                    self.win.setProperty("script.module.simplecache.cacheobjects",repr(cacheObjects).encode("utf-8"))

                #cleanup file cache objects
                if xbmcvfs.exists(DEFAULTCACHEPATH):
                    dirs, files = xbmcvfs.listdir(DEFAULTCACHEPATH)
                    n = datetime.datetime.now()
                    for file in files:

                        #check filebased cache for expired items
                        cachefile = DEFAULTCACHEPATH + file
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

    @staticmethod
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
    
    @staticmethod
    def get_cache_name( endpoint ):
        value = base64.encodestring(try_encode(endpoint)).decode("utf-8")
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
        value = unicode(re.sub('[^\w\s-]', '', value).strip().lower())
        value = unicode(re.sub('[-\s]+', '-', value))
        return value

    def get_cache_file( self, endpoint ):
        return DEFAULTCACHEPATH + self.get_cache_name(endpoint)

        
###### Utilities ##############################
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
        
def log_msg(msg, loglevel = xbmc.LOGNOTICE):
    if isinstance(msg, unicode):
        msg = msg.encode('utf-8')
    xbmc.log("Skin Helper Simplecache --> %s" %msg, level=loglevel)
