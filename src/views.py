
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

from .registry import all_caches
from django.shortcuts import redirect, render_to_response
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

@login_required
def view_all(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()
    caches = sorted(all_caches, key=lambda c: c.name)
    cache_data = [{'pretty_name': cache.pretty_name, 'hit_count': cache.hit_count, 'miss_count': cache.miss_count} for cache in caches]
    return render_to_response('argcache/view_all.html', {'caches': cache_data})

@login_required
def flush(request, cache_id):
    if not request.user.is_staff:
        return HttpResponseForbidden()
    cache = sorted(all_caches, key=lambda c: c.name)[int(cache_id)]
    cache.delete_all()
    return redirect(reverse('view_all'))
