""" Bulk-deletable cache objects. """
__author__    = "Individual contributors (see AUTHORS file)"
__date__      = "$DATE$"
__rev__       = "$REV$"
__license__   = "AGPL v.3"
__copyright__ = """
This file is part of the ESP Web Site
Copyright (c) 2009 by the individual contributors
  (see AUTHORS file)

The ESP Web Site is free software; you can redistribute it and/or
modify it under the terms of the GNU Affero General Public License
as published by the Free Software Foundation; either version 3
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public
License along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

Contact information:
MIT Educational Studies Program
  84 Massachusetts Ave W20-467, Cambridge, MA 02139
  Phone: 617-253-4882
  Email: esp-webmasters@mit.edu
Learning Unlimited, Inc.
  527 Franklin St, Cambridge, MA 02139
  Phone: 617-379-0178
  Email: web-team@learningu.org
"""

from django.core.cache import cache
from django.dispatch import Signal
from django.db.models import signals
from django.conf import settings

from esp.middleware import ESPError

from esp.cache.queued import add_lazy_dependency
from esp.cache.token import Token, SingleEntryToken
from esp.cache.key_set import specifies_key, token_list_for
from esp.cache.marinade import marinade_dish
from esp.cache.registry import register_cache
from esp.cache.sad_face import warn_if_loaded
from esp.cache.signals import cache_deleted

__all__ = ['ArgCache']

# XXX: For now, all functions must have known arity. No *args or
# **kwargs are allowed, but optional arguments are fine. This is done to
# avoid overcomplicating everything, especially this early. If we have a
# compelling reason to extend it, this can be modified later.


# TODO: Don't store each token with the final object, hash them together, to
# avoid a ridiculous blowup in memory. This will make it about as memory
# efficient as tiered caching. May be a performance hit though... not sure.
#
# I think it's worth it though... this also has the side effect that caches
# have tokens and then can be used as handles maybe? Kind of another way to
# express 1-1 dependencies... but offloading work from set() to get(), which
# isn't so nice... Still, perhaps some relations are hard to reverse.
#
# Also, can we pretend we never get a hash collision here?


# TODO: This scheme does not allow for sets that involve things like
# everything-below-this-DataTree-node, which could be very useful for UserBit
# stuff. At least the simplest version could fixed by implementing the
# BatchableCache thing and then extending to allow multiple keys per token
# (well, actually the token will just look at lots of keys without telling
# anyone). This also will allow for depending on param signature and stuff.
# However, this does not scale well. i.e., it's O(depth) work, which may be
# fine for one token, but several? Also, if some token does two such queries at
# once (say... V + Q...). it's O(depth^2) work. The hashing thing will help
# with memory, but still... Gack! I think this is not a blocker though. Tiered
# caching couldn't do this either... this is simply something we don't know how
# to implement at all, as far as I know.


# TODO: To be really useful, this system needs to track old values of fields,
# even though we usually don't do things like reassign Event to another
# Program. This shouldn't be hard... monkey patch the models on a as-needed
# basis.


# TODO: We need to be able to notice when a bunch of things got update and
# stuff...


# FIXME: Actually, this probably doesn't handle subclassing properly at all.
# This is unfortunate.
#
# Possibilities:
#
# 1. Delay until all models are initialized (DONE)
# 2. When connecting signals, make multiple connections for every subclass
#    and... do something smart about superclasses??
#    - I don't want to need a query just to check if this guy is an instance
#      of the class I'm interested in.
#    - Also, even if something of the right instance changed, what if I don't
#      care about any of the shared fields?
#
# 1. Connect to every model and, in the handler, check whether we care about
#    this one.
# 
# 1. Mike Price's common base class thing gives everything a unique name AND
#    can enforce a type value in there


# FIXME: Need a "nothing" key_set object that's distinct from None... purpose
# is to cancel things nicely in functions like
# "Program.objects.get_if_exists_otherwise"


# TODO: Refactor key_set things from is_wildcard to is_exact or something, so
# that we can extend this to more complex queries in the future. Perhaps each
# token has a can_handle() thing that sees if it can handle each query. This
# will likely depend on an asynchronous-cacher thing.


# TODO: Somehow collapse these duplicate reports... delay signals? Keep track
# of when we last set?  problem... multiple processes... I suppose we could use
# a "IPC" mechanism of the cache. Sigh.


# TODO: Depend on external factors (a version cookie on each function when
# needed) and the param signature


# TODO: Properly handle things like staticmethod and classmethod (?)


# FIXME: How to handle things like... ids don't change, but want to be careful
# with the objects themselves.


# TODO: Probably need to allow functions to return like... lists of dicts or
# something, but I'm not very happy with that... probably best to go for the
# more general tokens thing, which more-or-less depends on async caching


class ArgCache(object):
    """ Implements a cache that allows for selectively dropping bits of itself. """

    CACHE_NONE = {} # we could use a garbage string for this, but it's impossible to collide with the id of a dict.

    def __init__(self, name, params, cache=cache, timeout_seconds=None, *args, **kwargs):
        super(ArgCache, self).__init__(*args, **kwargs)

        if isinstance(params, list):
            params = tuple(params)
        self.name = name
        self.params = params
        self.cache = cache
        self.timeout_seconds = timeout_seconds
        self.tokens = []
        self.token_dict = {}
        self.locked = False

        # Mostly used to avoid recursion
        self.disabled = False

        # Init stats
        self.hit_count = 0
        self.miss_count = 0

        # Be able to invert param mapping
        self.param_dict = {}
        for i,param in enumerate(params):
            self.param_dict[param] = i

        # FIXME: Really ought to depend on param signature.
        #self.global_token = ExternalToken(name=name, provided_params=(), external=hash(params))
        self.global_token = Token(name=name, provided_params=(), cache=self.cache)
        self.add_token(self.global_token)

        # Calling in the constructor to avoid duplicates
        if warn_if_loaded():
            print "Dumping the cache out of paranoia..."
            self.delete_all()
        
        self.register()

    def _hit_hook(self, arg_list):
        if settings.CACHE_DEBUG:
            old_disabled, self.disabled = self.disabled, True
            print "Cache Hit! %s on %s" % (self.name, arg_list)
            self.disabled = old_disabled
        self.hit_count += 1

    def _miss_hook(self, arg_list):
        if settings.CACHE_DEBUG:
            old_disabled, self.disabled = self.disabled, True
            print "Cache Miss! %s on %s" % (self.name, arg_list)
            self.disabled = old_disabled
        self.miss_count += 1

    @property
    def pretty_name(self):
        return '%s(%s)' % (self.name, ', '.join(self.params))

    # @delay_method # Slightly nontrivial... duplicate-checker needs to know about stuff.
    def register(self):
        register_cache(self)

    # TODO: I really should make a signal thing that provides __get__ so that
    # it acts like a bound member function or something really awful like that.
    # In fact, I would not be surprised if Django eventually did this, so, for
    # insurance, _delete_signal is not a member of ArgCache. :-D
    def connect(self, handler):
        """ Connect handler to this cache's delete signal. """
        cache_deleted.connect(handler, sender=self, weak=False) # local functions will be used a lot, so no weak refs
    connect.alters_data = True
    def send(self, key_set):
        """ Internal: Send the signal. """
        cache_deleted.send(sender=self, key_set=key_set)
    send.alters_data = True

    def index_of_param(self, param):
        """ Should be internal, returns the index of a particular parameter. """
        if isinstance(param, int):
            # don't do anything if we already have an id
            return param
        if not self.param_dict.has_key(param):
            raise ESPError('Cache %s (params %s) error: %s is not a valid argument' % (self.name, self.param_dict, param))
        return self.param_dict[param]

    def delete_all(self):
        """ Dumps everything in this cache. """
        self.global_token.delete_filt(())
    delete_all.alters_data = True

    def key(self, arg_list):
        """ Returns a cache key, given a list of arguments. """
        return self.name + '|' + ':'.join([marinade_dish(arg) for arg in arg_list])

    def _token_keys(self, arg_list):
        """ Returns a list of keys to grab for all the tokens. """
        # TODO: Implement some sort of asynchronous caching for batching get_many
        token_keys = []
        for token in self.tokens:
            token_keys.append(token.key(arg_list))
        return token_keys

    def add_token(self, token):
        """ Adds the given token to this cache. """
        self.tokens.append(token)
        self.token_dict[token.provided_params] = token
        token.cache_obj = self
    add_token.alters_data = True

    def get_or_create_token(self, params):
        """ Ensures that a token exists for the given subset of the parameters. """
        if len(params) == len(self.params):
            # Make a fake proxy token
            # HACK of sorts... do NOT add it, as it's not really there
            return SingleEntryToken(self)
        provided_params = [self.index_of_param(param) for param in params]
        provided_params.sort()
        provided_params = tuple(provided_params)
        if self.token_dict.has_key(provided_params):
            return self.token_dict[provided_params]
        tname = ':'.join([self.params[i] for i in provided_params])
        tname = self.name + '|' + tname
        t = Token(tname, provided_params, cache=self.cache)
        self.add_token(t)
        return t
    get_or_create_token.alters_data = True

    def find_token(self, key_set):
        """ Return a token that can delete this key set. """
        # Do we have a perfect match?
        # FIXME: This is really awful...
        provided_params = [self.index_of_param(param) for param in token_list_for(key_set)]
        provided_params.sort()
        provided_params = tuple(provided_params)

        if self.token_dict.has_key(provided_params):
            return self.token_dict[provided_params]
        # FIXME: Come up with a smarter fallback solution count number of
        # roundings? instead of contains, return a "closeness" heuristic?
        for token in reversed(self.tokens):
            if token.contains(key_set):
                return token

    def get(self, arg_list, default=None):
        """ Get the value of the cache at arg_list (which can be a tuple). """
        if self.disabled:
            return default

        key = self.key(arg_list)

        # gather keys
        keys_to_get = [key] + self._token_keys(arg_list)

        # extract values
        ans_dict = self.cache.get_many(keys_to_get)
        wrapped_value = ans_dict.get(key, self.CACHE_NONE)
        if wrapped_value is self.CACHE_NONE:
            self._miss_hook(arg_list)
            return default
        
        try:
            # check tokens
            if len(wrapped_value) != len(keys_to_get):
                # shhhh... that value wasn't really there
                self.cache.delete(key)
                self._miss_hook(arg_list)
                return default
            for tvalue, tkey in zip(wrapped_value[1:], keys_to_get[1:]):
                saved_value = ans_dict.get(tkey, self.CACHE_NONE)
                # token mismatch!
                if saved_value is self.CACHE_NONE or saved_value != tvalue:
                    # shhhh... that value wasn't really there
                    self.cache.delete(key)
                    self._miss_hook(arg_list)
                    return default

            # okay, it's good
            self._hit_hook(arg_list)
            return wrapped_value[0]

        except Exception: # Don't die on errors, e.g. if wrapped_value is not a tuple/list
            self._miss_hook(arg_list)
            return default

    def set(self, arg_list, value, timeout_seconds=None):
        """ Set the value of the cache at arg_list (which can be a tuple). """
        if self.disabled:
            return

        key = self.key(arg_list)

        # gather keys
        token_keys = self._token_keys(arg_list)

        # extract what values we can
        #  we use get_many here to optimize the common case: all tokens already present
        ans_dict = self.cache.get_many(token_keys)

        # regenerate missing tokens
        for tkey, token in zip(token_keys, self.tokens):
            if not ans_dict.has_key(tkey):
                ans_dict[tkey] = token.value_args(arg_list)

        # gather token values
        wrapped_value = [value]
        for tkey in token_keys:
            wrapped_value.append(ans_dict[tkey])

        if timeout_seconds is None:
            timeout_seconds = self.timeout_seconds
            
        self.cache.set(key, wrapped_value, timeout_seconds)
    set.alters_data = True

    def delete(self, arg_list):
        """ Delete the value of the cache at arg_list (which can be a tuple). """
        key = self.key(arg_list)
        self.cache.delete(key)
        key_set = {}
        for i,arg in enumerate(arg_list):
            key_set[self.params[i]] = arg
        self.send(key_set=key_set)
    delete.alters_data = True

    def delete_key_set(self, key_set):
        """ Delete everything in this key_set, rounding up if necessary. """

        if settings.CACHE_DEBUG:
            print "Dumping from", self.name, "keyset", key_set

        # TODO: Would be nicer if we could just make a
        # proxy token for the single-element case
        arg_list = self.is_arg_list(key_set)
        if arg_list:
            return self.delete(arg_list)
        else:
            token = self.find_token(key_set)
            token.delete_key_set(key_set, send_signal=False) # We can send a more accurate signal
            self.send(key_set=key_set)
    delete_key_set.alters_data = True

    def delete_key_sets(self, list_or_set):
        """ Delete one or multiple (including nested lists) key sets. 
            - Michael P 11/1/2009
        """
        if isinstance(list_or_set, list):
            for item in list_or_set:
                self.delete_key_sets(item)
        else:
            self.delete_key_set(list_or_set)
    delete_key_sets.alters_data = True

    def has_key(self, arg_list):
        """ Returns true if arg_list is cached. """
        return self.get(arg_list,default=self.CACHE_NONE) is not self.CACHE_NONE

    def is_arg_list(self, key_set):
        """ Does this key_set specify everything? """
        arg_list = []
        for param in self.params:
            if specifies_key(key_set, param):
                arg_list.append(key_set[param])
            else:
                return False
        return arg_list

    def depend_on_model(self, Model, key_set={}, create_token=True):
        """
        Dump parts of this cache when anything in the Model changes.

        key_set is the key_set to dump. If not provided, the entire cache is
        dumped. If create_token is True, we ensure a token exists to delete
        this.
        
        This function is equivalent to self.depend_on_row(Model, lambda
        instance: key_set) with the proper token created. We probably could
        replace this function with that, but oh well. It's... marginally more
        efficient.
        """
        # Silently fail. This means the object has been double-loaded (Thanks,
        # Python/Django double-import)
        if self.locked:
            return
        def resolve_depend_on_model(Model):
            if create_token:
                self.get_or_create_token(token_list_for(key_set))
            def delete_cb(sender, **kwargs):
                self.delete_key_sets(key_set)
            signals.post_save.connect(delete_cb, sender=Model, weak=False)
            signals.pre_delete.connect(delete_cb, sender=Model, weak=False)
        add_lazy_dependency(self, Model, resolve_depend_on_model)
    depend_on_model.alters_data = True

    def depend_on_row(self, Model, selector, filter=None):
        """
        Depend on a row of a Model when a row of this Model changes.

        When a row is changed, selector is called to determine the key_set
        to evict. selector should be of the form

        def selector(instance):
            return {'class' : instance.parent_class}

        Because of how common the case is, if selector is a string, we create
        the token automatically and use lambda instance : {selector: instance}
        as the mapping function.
        """
        # Silently fail. This means the object has been double-loaded (Thanks,
        # Python/Django double-import)
        if self.locked:
            return
        if filter is None:
            filter = lambda instance: True
        if isinstance(selector, str):
            # Special-case this
            selector_str = selector
            selector = lambda instance: {selector_str: instance}
            # Make the token
            token = self.get_or_create_token((selector_str,))

        def resolve_depend_on_row(Model):
            if Model is None:
                raise ESPError("Attempting to depend on Model None... this is a pretty dumb thing to do.")
            def delete_cb(sender, instance, **kwargs):
                if not filter(instance):
                    return None
                new_key_set = selector(instance)
                if new_key_set is not None:
                    self.delete_key_sets(new_key_set)
            signals.post_save.connect(delete_cb, sender=Model, weak=False)
            signals.pre_delete.connect(delete_cb, sender=Model, weak=False)
        add_lazy_dependency(self, Model, resolve_depend_on_row)
    depend_on_row.alters_data = True

    def depend_on_cache(self, cache_obj, mapping_func, filter=None):
        """
        Depend on another cache, cache_obj, using mapping_func.
        mapping_func should take a key_set for cache_obj and return a key_set
        for self. Empty sets represented by None. It should have the form...
        
        def mapping_func(arg1=wildcard, arg2=wildcard, arg3=wildcard, **kwargs):
            return { something : something_else, .... }

        (missing arguments default to * and kwargs collects unused ones.)

        Also, call get_or_create_token() to make the tokens that you need.
        """
        # Silently fail. This means the object has been double-loaded (Thanks,
        # Python/Django double-import)
        if self.locked:
            return
        if filter is None:
            filter = lambda **kwargs: True
        # HACK: allow cached methods of models to be specified as strings
        # "app.Model.method"
        method_name = None
        if isinstance(cache_obj, basestring):
            cache_obj, method_name = cache_obj.rsplit(".", 1)
        def resolve_depend_on_cache(cache_obj):
            if method_name is not None:
                cache_obj = getattr(cache_obj, method_name)
            def delete_cb(sender, key_set, **kwargs):
                if not filter(**key_set):
                    return None
                new_key_set = mapping_func(**key_set)
                if new_key_set is not None:
                    self.delete_key_sets(new_key_set)
            # TODO: Handle timeouts and take the min of a timeout
            cache_obj.connect(delete_cb)
        add_lazy_dependency(self, cache_obj, resolve_depend_on_cache)
    depend_on_cache.alters_data = True

    def depend_on_m2m(self, Model, m2m_field, add_func, rem_func=None, filter=None):
        """
        Depend on an m2m relation, field m2m_field of model Model, using
        add_func and rem_func. They should have the form

        def add_func(instance, object):
            return { .... }

        If rem_func is omitted, add_func is used.
        """
        # Silently fail. This means the object has been double-loaded (Thanks,
        # Python/Django double-import)
        if self.locked:
            return
        if rem_func is None:
            rem_func = add_func
        if filter is None:
            filter = lambda instance, object: True

        def resolve_depend_on_m2m(Model):
            IntermediateModel = getattr(Model, m2m_field).through
            def change_cb(sender, instance, action, model, pk_set, **kwargs):
                if action == "post_add":
                    objects = model.objects.filter(pk__in=pk_set)
                    selector = add_func
                elif action == "pre_remove":
                    objects = model.objects.filter(pk__in=pk_set)
                    selector = rem_func
                elif action == "pre_clear":
                    objects = model.objects.all()
                    selector = rem_func
                else:
                    return
                if isinstance(instance, Model):
                    for object in objects:
                        do_delete(instance, object, selector, filter)
                else: # reversed m2m; switch instance and object
                    for object in objects:
                        do_delete(object, instance, selector, filter)
            def do_delete(instance, object, selector, filter):
                if not filter(instance, object):
                    return None
                new_key_set = selector(instance, object)
                if new_key_set is not None:
                    self.delete_key_sets(new_key_set)
            signals.m2m_changed.connect(change_cb, sender=IntermediateModel, weak=False)
        add_lazy_dependency(self, Model, resolve_depend_on_m2m)
