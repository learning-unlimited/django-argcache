
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

import importlib
from django.apps import AppConfig, apps

from .registry import _finalize_caches, _lock_caches

class ArgCacheConfig(AppConfig):
    """ Makes sure all caches are inserted. Replacement for cache_loader. """

    name = 'argcache'

    def ready(self):
        # Import caches from each installed app
        for app_config in apps.get_app_configs():
            try:
                importlib.import_module('.caches', app_config.name)
            except ImportError as e:
                # Works for vanilla python 2.7 and PyPy 2.7 (needed for the time being for GHA)
                if len(e.args) > 0 and e.args[0].startswith('No module named'):
                    continue
                raise

        # Fix up the queued events
        _finalize_caches()
        _lock_caches()
