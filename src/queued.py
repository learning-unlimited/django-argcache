""" General object with queuable actions. """
__author__    = "Individual contributors (see AUTHORS file)"
__date__      = "$DATE$"
__rev__       = "$REV$"
__license__   = "AGPL v.3"
__copyright__ = """
This file is part of ArgCache.
Copyright (c) 2015 by the individual contributors
  (see AUTHORS file)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import types

from django.apps import apps
from django.db.models import signals

pending_lookups = {}

def add_lazy_dependency(self, obj, operation):
    """ If obj is a function (thunk), delay operation; otherwise execute immediately. """
    if isinstance(obj, basestring):
        app_label, model_name = obj.split(".")
        try:
            # This is a private API, please fix it!
            model = apps.get_registered_model(app_label, model_name)
        except LookupError:
            key = (app_label, model_name)
            value = operation
            pending_lookups.setdefault(key, []).append(value)
        else:
            operation(model)
    elif isinstance(obj, types.FunctionType):
        import warnings
        warnings.warn("Using lambdas to thunk dependencies is deprecated. Use strings instead.", DeprecationWarning, stacklevel=3)
        # HACK: stick the lambda into pending_lookups as a key,
        # which will be processed in do_all_pending.
        key = obj
        value = operation
        pending_lookups.setdefault(key, []).append(value)
    else:
        operation(obj)

def do_pending_lookups(sender, **kwargs):
    """ Handle any pending dependencies on the sending model. Sent from class_prepared. """
    key = (sender._meta.app_label, sender.__name__)
    for operation in pending_lookups.pop(key, []):
        operation(sender)

signals.class_prepared.connect(do_pending_lookups)

def do_all_pending():
    # process any pending lookups that are actually lambdas.
    for key in pending_lookups:
        assert isinstance(key, types.FunctionType)
        for operation in pending_lookups.get(key, []):
            operation(key())
