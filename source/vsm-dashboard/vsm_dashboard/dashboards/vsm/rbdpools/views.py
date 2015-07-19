# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 Intel Corporation, All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
from django.utils.translation import ugettext_lazy as _
from django.core.urlresolvers import reverse_lazy

from horizon import exceptions
from horizon import tables
from horizon import forms

from vsm_dashboard.api import vsm as vsmapi
from vsm_dashboard.dashboards.vsm.poolsmanagement import utils
from .form import CreatePool
from .tables import ListPoolTable
from .tables import ListPresentPoolTable
from .utils import GenAuthToken
from .utils import list_cinder_service
import os

import json
from django.http import HttpResponse
LOG = logging.getLogger(__name__)

class ModalEditTableMixin(object):
    def get_template_names(self):
        if self.request.is_ajax():
            if not hasattr(self, "ajax_template_name"):
                # Transform standard template name to ajax name (leading "_")
                bits = list(os.path.split(self.template_name))
                bits[1] = "".join(("_", bits[1]))
                self.ajax_template_name = os.path.join(*bits)
            template = self.ajax_template_name
        else:
            template = self.template_name
        return template

    def get_context_data(self, **kwargs):
        context = super(ModalEditTableMixin, self).get_context_data(**kwargs)
        context['verbose_name'] = getattr(self, "verbose_name", "")
        context['submit_btn'] = getattr(self, "submit_btn", {})
        if self.request.is_ajax():
            context['hide'] = True
        return context

class IndexView(tables.DataTableView):
    table_class = ListPoolTable
    template_name = 'vsm/rbdpools/index.html'

    def get_data(self):
        pools = []
        pool_usages = []
        # TODO pools status
        try:
            pools = vsmapi.pool_list(self.request,)
            pool_usages = vsmapi.pool_usages(self.request)
            logging.debug("resp body in view: %s" % pools)
        except:
            exceptions.handle(self.request,
                              _('Unable to retrieve storage pool list. '))
        pool_usage_dict = {}
        for usage in pool_usages:
            pool_usage_dict.setdefault(str(usage.pool_id), usage)

        for pool in pools:
            pool['id'] = str(pool['id'])
            if pool['id'] in pool_usage_dict:
                pool['attach_status'] = pool_usage_dict[pool['id']].attach_status
            else:
                pool['attach_status'] = "no"

        pools = [x for x in pools if x['tag'] != "SYSTEM" and not x['erasure_code_status']
                     and not str(x['cache_tier_status']).startswith("Cache pool for")]
        return pools

class PresentPoolsView(tables.DataTableView):
    table_class = ListPresentPoolTable
    template_name = 'vsm/rbdpools/rbdsaction.html'
    verbose_name = "Present Pools"

    def get_data(self):
        pools = []
        pool_usages = []
        # TODO pools status
        try:
            pools = vsmapi.pool_list(self.request,)
            pool_usages = vsmapi.pool_usages(self.request)
            logging.debug("resp body in view: %s" % pools)
        except:
            exceptions.handle(self.request,
                              _('Unable to retrieve storage pool list. '))
        pool_usage_dict = {}
        for usage in pool_usages:
            pool_usage_dict.setdefault(str(usage.pool_id), usage)

        for pool in pools:
            pool['id'] = str(pool['id'])
            if pool['id'] in pool_usage_dict:
                pool['attach_status'] = pool_usage_dict[pool['id']].attach_status
            else:
                pool['attach_status'] = "no"

        pools = [x for x in pools if x['tag'] != "SYSTEM"]
        pools = [x for x in pools if x['attach_status'] == "no"]
        pools = [x for x in pools if x['tag'] != "SYSTEM" and not x['erasure_code_status']
             and not str(x['cache_tier_status']).startswith("Cache pool for")]
        return pools

class CreateView(forms.ModalFormView):
    form_class = CreatePool
    template_name = 'vsm/flocking/create.html'
    success_url = reverse_lazy('horizon:vsm:rbdpools:index')

def PoolsAction(request, action):
    data = json.loads(request.body)
    # TODO add cluster_id in data
    if not len(data):
        status = "error"
        msg = "No pool selected"
    else:
        # TODO add cluster_id in data
        for i in range(0, len(data)):
            data[i]['cluster_id'] = 1
        # TODO add cluster_id in data

        if action == "present":
            print data
            pools = []
            for x in data:
                pools.append({'id': x['id'], 'cinder_volume_host': x['cinder_volume_host']})
            print "========Start Present Pools==========="
            result = vsmapi.present_pool(request, pools)
            print result
            host_list = ""
            for host in result['host']:
                host_list = host + "," + host_list
            if result['status'] == "bad":
                status = "warning"
                msg = "Not found crudini commmand in host: %s" % host_list
            elif result['status'] == "unreachable":
                status = "warning"
                msg = "Please check ssh with no password between vsm controller and host: %s" % host_list
            else:
                status = "info"
                msg = "Begin to Present Pools!"
            print "========End Present Pools==========="

    resp = dict(message=msg, status=status, data="")
    resp = json.dumps(resp)
    return HttpResponse(resp)

def get_select_data(request):
    appnode = vsmapi.appnode_list(request)[0]
    tenant_name = appnode.os_tenant_name
    username = appnode.os_username
    password = appnode.os_password
    auth_url = appnode.os_auth_url
    auth_host = auth_url.split(":")[1][2:]
    genauthtoken = GenAuthToken(tenant_name, username, password, auth_host)
    token, tenant_id = genauthtoken.get_token()
    cinder_service_list = list_cinder_service(auth_host, token, tenant_id)

    cinder_volume_down_list = []
    for cinder in cinder_service_list:
        if cinder["state"] == "down":
            cinder_volume_down_list.append(cinder)

    cinder_service = []
    value = 0
    if len(cinder_volume_down_list) == 0:
        for cinder in cinder_service_list:
            if cinder["binary"] == "cinder-volume":
                cinder.update({"value": value})
                value = value + 1
                cinder_service.append(cinder)
    else:
        for cinder in cinder_service_list:
            if cinder["binary"] == "cinder-volume" and \
                            "@" in cinder["host"]:
                host = cinder["host"].split("@")[0]
                if host not in [x["host"] for x in cinder_service_list]:
                    cinder.update({"value": value})
                    value = value + 1
                    cinder_service.append(cinder)
            elif cinder["binary"] == "cinder-volume" and \
                            "@" not in cinder["host"]:
                cinder.update({"value": value})
                value = value + 1
                cinder_service.append(cinder)

    data = tuple(cinder_service)
    return HttpResponse(json.dumps(data))