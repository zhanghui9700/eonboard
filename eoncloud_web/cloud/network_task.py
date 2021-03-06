#-*-coding=utf-8-*- 

import datetime
import logging
import time

from django.conf import settings

from celery import app
from cloud_utils import (create_rc_by_network, create_rc_by_subnet,
                         create_rc_by_router, create_rc_by_floating,
                         create_rc_by_security,  create_rc_by_udc)

from biz.network.models import Network, Subnet, Router, RouterInterface
from biz.firewall.models import Firewall, FirewallRules
from biz.floating.settings import (FLOATING_AVAILABLE, FLOATING_RELEASED,
                                   FLOATING_BINDED, FLOATING_ERROR,
                                   RESOURCE_TYPE)
from biz.network.settings import NETWORK_STATE_ACTIVE, NETWORK_STATE_ERROR
from biz.instance.models import Instance
from biz.lbaas.models import BalancerPool
from biz.lbaas.models import BalancerVIP

from api import neutron
from api import network

LOG = logging.getLogger("cloud.tasks")

ACTIVE = 1
DELETED = 2
ERROR = 3 


def create_default_private_network(instance):
    # create network
    try:
        return Network.objects.get(pk=instance.network_id)
    except Network.DoesNotExist:
        pass

    network = Network.objects.filter(
        is_default=True, status__in=[0, 1], user=instance.user,
        user_data_center=instance.user_data_center)

    if network.exists():
        return network[0]

    network = Network.objects.create(
        name=settings.DEFAULT_NETWORK_NAME, status=0, is_default=True,
        user=instance.user,
        user_data_center=instance.user_data_center)

    subnet = Subnet.objects.create(
        name=settings.DEFAULT_SUBNET_NAME, network=network,
        address="172.31.0.0/24", ip_version=4, status=0, user=instance.user,
        user_data_center=instance.user_data_center)

    router = Router.objects.create(
        name=settings.DEFAULT_ROUTER_NAME, status=0, is_default=True,
        is_gateway=True, user=instance.user,
        user_data_center=instance.user_data_center)

    create_network(network)
    create_subnet(subnet)
    router_create_task(router)
    router_add_gateway_task(router)
    attach_network_to_router(network.id, router.id, subnet.id)

    return network


@app.task
def create_network(network):
    rc = create_rc_by_network(network)
    network_params = {'name': "network-%s" % network.id, "admin_state_up": True}
    LOG.info("Start to create network, id:[%s], name[%s]",
             network.id, network.name)
    try:
        net = neutron.network_create(rc, **network_params)

        network.network_id = net.id
        network.status = NETWORK_STATE_ACTIVE
        network.save()
    except Exception as ex:
        network.status = NETWORK_STATE_ERROR
        network.save()
        LOG.exception("Failed to create network, id:[%s], name[%s], "
                      "exception:[%s]",
                      network.id, network.name, ex)
        raise ex

    return network


@app.task
def delete_network(network):
    rc = create_rc_by_network(network)
    LOG.info("Start to delete network, id:[%s], name[%s]",
             network.id, network.name)
    try:

        subnet_set = Subnet.objects.filter(network_id=network.id, deleted=False)
        for subnet in subnet_set:
            delete_subnet(subnet)

        neutron.network_delete(rc, network.network_id)

        network.network_id = None
        network.deleted = True
        network.save()
    except Exception as ex:
        network.status = NETWORK_STATE_ERROR
        network.save()
        LOG.exception("Failed to delete network, id:[%s], name[%s], msg:[%s]",
                      network.id, network.name, ex)
        raise ex

    return network


@app.task
def create_subnet(subnet=None):
    rc = create_rc_by_subnet(subnet)

    subnet_params = {"network_id": subnet.network.network_id,
                     "name": "subnet-%s" % subnet.id,
                     "cidr": subnet.address,
                     "ip_version": subnet.ip_version,
                     "dns_nameservers": settings.DNS_NAMESERVERS,
                     "enable_dhcp": True}

    LOG.info("Start to create subnet, id[%s], name[%s]",
             subnet.id, subnet.name)
    try:
        sub = neutron.subnet_create(rc, **subnet_params)

        subnet.subnet_id = sub.id
        subnet.status = NETWORK_STATE_ACTIVE
        subnet.save()
    except Exception as ex:
        subnet.status = NETWORK_STATE_ERROR
        subnet.save()
        LOG.exception("Failed to create subnet, id:[%s], name:[%s], msg:[%s]",
                      subnet.id, subnet.name, ex)
        raise ex

    return subnet


@app.task
def delete_subnet(subnet):
    rc = create_rc_by_subnet(subnet)
    try:
        LOG.info("Start to delete subnet, id[%s], name[%s]",
                 subnet.id, subnet.name)
        neutron.subnet_delete(rc, subnet.subnet_id)

        subnet.deleted = True
        subnet.save()
    except Exception as ex:
        subnet.status = NETWORK_STATE_ERROR
        subnet.save()
        LOG.exception("Failed to delete subnet, id:[%s], name:[%s], msg:[%s]",
                      subnet.id, subnet.name, ex)
        raise ex

    return subnet


@app.task
def router_create_task(router=None):
    rc = create_rc_by_router(router)

    router_params = {"name": "router-%s" % router.id,
                     "distributed": False,
                     "ha": False}

    try:
        rot = neutron.router_create(rc, **router_params)

        router.router_id = rot.id
        if router.is_gateway:
            router_add_gateway_task(router)
        router.status = NETWORK_STATE_ACTIVE
        router.save()
    except Exception as ex:
        router.status = NETWORK_STATE_ERROR
        router.save()
        LOG.info("delete router error,id:[%s], msg:[%s]" % (router.id, ex))
        raise ex

    return router


@app.task
def router_delete_task(router=None):
    rc = create_rc_by_router(router)

    LOG.info("delete router,id:[%s],name[%s]" % (router.id, router.name))
    try:
        ro = neutron.router_delete(rc, router.router_id)
        router.router_id = None
        router.deleted = True
        router.save()
    except Exception as ex:
        router.status = NETWORK_STATE_ERROR
        router.save()
        LOG.info("delete router error,id:[%s],name[%s],msg:[%s]" % (network.id, network.name, ex))
        raise ex

    return network


@app.task
def router_add_gateway_task(router=None):
    rc = create_rc_by_router(router)
    # find external network
    search_opts = {'router:external': True}
    networks = neutron.network_list(rc, **search_opts)
    ext_net = filter(lambda n: n.name.lower() == router.user_data_center.data_center.ext_net, networks)
    ext_net_id = None
    if ext_net and len(ext_net) > 0:
        ext_net_id = ext_net[0].id

    # set external gateway
    neutron.router_add_gateway(rc, router.router_id, ext_net_id)
    time.sleep(5) 

    # update cloud db router gateway info
    os_router = neutron.router_get(rc, router.router_id)
    ext_fixed_ips = os_router["external_gateway_info"].get("external_fixed_ips", [])
    router.gateway = ext_fixed_ips[0].get("ip_address") if ext_fixed_ips else "---"
    router.status = NETWORK_STATE_ACTIVE
    router.is_gateway = True
    router.save()

    return True


@app.task
def router_remove_gateway_task(router=None):
    if not router:
        return
    rc = create_rc_by_router(router)
    neutron.router_remove_gateway(rc, router.router_id)
    router.gateway = ''
    router.status = NETWORK_STATE_ACTIVE
    router.is_gateway = False
    router.save()


@app.task
def create_network_and_subnet(network, subnet):
    create_network(network)
    create_subnet(subnet)


@app.task
def attach_network_to_router(network_id, router_id, subnet_id):

    network = Network.objects.get(pk=network_id)
    router = Router.objects.get(pk=router_id)
    subnet = Subnet.objects.get(pk=subnet_id)

    rc = create_rc_by_router(router)

    try:
        LOG.info("Start to attach network[%s] to router[%s]",
                 network.name, router.name)
        router_inf = neutron.router_add_interface(
            rc, router.router_id, subnet_id=subnet.subnet_id)
    except Exception as e:
        LOG.exception("Failed to attach network[%s] to router[%s], "
                      "exception:%s",  network.name, router.name, e)
        network.change_status(NETWORK_STATE_ERROR)

    else:
        RouterInterface.objects.create(
            network_id=network_id, router=router, subnet=subnet,
            user=subnet.user, user_data_center=subnet.user_data_center,
            os_port_id=router_inf['port_id'])

        network.change_status(NETWORK_STATE_ACTIVE)


@app.task
def detach_network_from_router(network_id):

    network = Network.objects.get(pk=network_id)
    subnet = network.subnet_set.filter(deleted=False)[0]
    rc = create_rc_by_network(network)
    interface_set = RouterInterface.objects.filter(network_id=network.id,
                                                   subnet=subnet, deleted=False)

    LOG.info("Start to detach network[%s]", network.name)

    try:
        for router_interface in interface_set:

            LOG.info("Start to delete router interface, router:[%s], "
                     "subnet[%s], id:[%s], port_id:[%s]",
                     router_interface.router.name, router_interface.subnet.name,
                     router_interface.id, router_interface.os_port_id)
            neutron.router_remove_interface(rc,
                                            router_interface.router.router_id,
                                            subnet.subnet_id,
                                            router_interface.os_port_id)

            router_interface.fake_delete()
    except Exception as e:
        LOG.exception("Failed to delete router interface, router:[%s], "
                      "subnet[%s], id:[%s], port_id:[%s], exception:%s",
                      router_interface.router.name,
                      router_interface.subnet.name,
                      router_interface.id, router_interface.os_port_id, e)
        network.change_status(NETWORK_STATE_ERROR)
        raise e
    else:
        network.change_status(NETWORK_STATE_ACTIVE)


@app.task
def allocate_floating_task(floating=None):
    rc = create_rc_by_floating(floating)
    LOG.info("Begin to allocate floating, [%s]" % floating.id);
    pools = network.floating_ip_pools_list(rc)
    ext_net = filter(lambda n: n.name.lower() == \
                    floating.user_data_center.data_center.ext_net, pools)
    ext_net_id = None
    if ext_net and len(ext_net) > 0:
        ext_net_id = ext_net[0].id
    if ext_net_id: 
        try:
            fip = network.tenant_floating_ip_allocate(rc, pool=ext_net_id)
            floating.ip = fip.ip
            floating.status = FLOATING_AVAILABLE
            floating.uuid = fip.id
            floating.save()
            LOG.info("End to allocate floating, [%s][%s]" % (floating.id, fip.ip));
        except Exception as e:
            floating.status = FLOATING_ERROR
            floating.save()
            LOG.exception(e)
            LOG.info("End to allocate floating, [%s][exception]" % floating.id);
    else:
        floating.status = FLOATING_ERROR
        floating.save()
        LOG.info("End to allocate floating, [%s][---]" % floating.id);


def floating_release(floating, **kwargs):
    rc = create_rc_by_floating(floating)
    result = True
    if floating.uuid:
        result = network.tenant_floating_ip_release(rc, floating.uuid)
        LOG.info("release floating associate instance, [%s]" % result)
    
    floating.status = FLOATING_RELEASED
    floating.deleted = 1
    floating.delete_date = datetime.datetime.now()
    floating.save()

    if floating.ip:
        ins = Instance.objects.filter(public_ip=floating.ip)
        ins.update(public_ip=None)

    LOG.info("floating action, [%s][relese][%s]" % (floating.id, result));


def floating_associate(floating, **kwargs):
    resource_type_dict = dict(RESOURCE_TYPE)
    resource_type = kwargs.get('resource_type')[0]
    resource = kwargs.get('resource')[0]
    if resource:
        rc = create_rc_by_floating(floating)
        ports = None
        resource_obj = None

        if resource_type_dict[str(resource_type)] == 'INSTANCE':
            ins = Instance.objects.get(pk=resource)
            resource_obj = ins
            if neutron.is_neutron_enabled(rc):
                ports = network.floating_ip_target_get_by_instance(rc, ins.uuid)
            else:
                ports = ins.uuid
        elif resource_type_dict[resource_type] == 'LOADBALANCER':
            pool = BalancerPool.objects.get(pk=resource)
            if not pool or not pool.vip:
                floating.status = FLOATING_AVAILABLE
                floating.save()
                return None
            resource_obj = pool
            ports = pool.vip.port_id+"_"+pool.vip.address

        if not ports:
            LOG.info("floating action, resourceType[%s],[%s][associate][ins:%s] ports is None" % (resource_type_dict[resource_type], floating.id, resource));
            floating.status = FLOATING_AVAILABLE
            floating.save()
            return

        LOG.info("floating action, [%s][associate][ins:%s][ports:%s]" % (
                            floating.id, resource, ports))
        try:
            network.floating_ip_associate(rc, floating.uuid, ports)
            if len(ports.split('_')) > 1:
                port, fixed_ip = ports.split('_')
            else:
                port, fixed_ip = ports, ports
            floating.resource = resource
            floating.resource_type = resource_type
            floating.status = FLOATING_BINDED
            floating.fixed_ip = fixed_ip
            floating.port_id = port
            floating.save()
            if resource_type_dict[str(resource_type)] == 'INSTANCE':
                resource_obj.public_ip = floating.ip
                resource_obj.save()
            elif resource_type_dict[resource_type] == 'LOADBALANCER':
                vip = BalancerVIP.objects.get(pk=resource_obj.vip.id)
                vip.public_address = floating.ip
                vip.save()
        except Exception as e:
            LOG.exception(e)
            floating.status = FLOATING_AVAILABLE
            floating.save()
    else:
        LOG.info("floating action, [%s][associate] no ins_id" % floating.id);


def floating_disassociate(floating, **kwargs):
    rc = create_rc_by_floating(floating)
    LOG.info("floating action, [%s][disassociate][port:%s]" % (floating.id, floating.port_id));
    try:
        if floating.uuid and floating.port_id:
            network.floating_ip_disassociate(rc, floating.uuid, floating.port_id)

        if floating.resource_type == 'INSTANCE':
            ins = Instance.objects.get(pk=floating.resource)
            ins.public_ip = None
            ins.save()
        elif floating.resource_type == 'LOADBALANCER':
            pool = BalancerPool.objects.get(pk=floating.resource)
            vip = BalancerVIP.objects.get(pk=pool.vip.id)
            vip.public_address = None
            vip.save()
        #floating.instance = None
        floating.resource = None
        floating.resource_type = None
        floating.status = FLOATING_AVAILABLE
        floating.fixed_ip = None
        floating.port_id = None
        floating.save()
    except Exception as e:
        return False

        
@app.task
def floating_action_task(floating=None, act=None, **kwargs):
    LOG.info("Begin to floating action, [%s][%s]" % (floating.id, act));
    try:
        globals()["floating_%s" % act](floating, **kwargs) 
    except Exception as e:
        LOG.exception(e)

    LOG.info("End floating action, [%s][%s]" % (floating.id, act));


@app.task
def security_group_create_task(firewall=None):
    if not firewall:
        return
    rc = create_rc_by_security(firewall)
    security_group = network.security_group_create(rc, firewall.name, firewall.desc)
    firewall.firewall_id = security_group.id
    firewall.save()


@app.task
def security_group_delete_task(firewall=None):
    if not firewall:
        return
    rc = create_rc_by_security(firewall)
    try:
        security_group = network.security_group_delete(rc, firewall.firewall_id)
        firewall.firewall_id = ""
        firewall.deleted = True
        firewall.save()
        firewall_rule_set = FirewallRules.objects.filter(firewall=firewall.id)
        if not firewall_rule_set:
            return
        for rule in firewall_rule_set:
            rule.firewall_rules_id = ''
            rule.deleted = True
            rule.save()
    except Exception as e:
        LOG.error("Firewall delete error, msg: %s" % e)
        raise e


@app.task
def security_group_rule_create_task(firewall_rule=None):
    if not firewall_rule:
        return
    rc = create_rc_by_security(firewall_rule)

    try:
        rule = network.security_group_rule_create(rc, parent_group_id=firewall_rule.firewall.firewall_id,
                                           direction=firewall_rule.direction,
                                           ethertype=firewall_rule.ether_type,
                                           ip_protocol=firewall_rule.protocol,
                                           from_port=firewall_rule.port_range_min,
                                           to_port=firewall_rule.port_range_max,
                                           cidr=firewall_rule.remote_ip_prefix,
                                           group_id=firewall_rule.remote_group_id)
        firewall_rule.firewall_rules_id = rule.id
        firewall_rule.save()
    except Exception as e:
        firewall_rule.delete()
        raise e


@app.task
def security_group_rule_delete_task(firewall_rule=None):
    if not firewall_rule:
        return

    rc = create_rc_by_security(firewall_rule)
    try:
        network.security_group_rule_delete(rc, firewall_rule.firewall_rules_id)
        firewall_rule.firewall_rules_id = ''
        firewall_rule.deleted = True
        firewall_rule.save()
    except Exception as e:
        LOG.info("Delete firewall rule error %s" % e)
        raise e


@app.task
def server_update_security_groups_task(instance, firewall=None):
    if not firewall:
        return
    rc = create_rc_by_security(firewall)
    try:
        LOG.info("Update server security group ,server_id[%s],security_group[%s]" % (instance.uuid, firewall.firewall_id))
        network.server_update_security_groups(rc, instance.uuid, [firewall.firewall_id])
    except Exception as e:
        LOG.error("Update server security group error, msg: %s" % e)
        raise e


def edit_default_security_group(user, udc):
    rc = create_rc_by_udc(udc) 
    sec_group_list = network.security_group_list(rc)
    default_sec_group = None
    for sec_group in sec_group_list:
        if sec_group.name == "default":
            default_sec_group = sec_group
            break
    if default_sec_group is None:
        LOG.error("default security group not found.instance:[%s], project:[%s]" \
                 % (instance.id, instance.user_data_center.tenant_name))
        return
    firewall = Firewall.objects.create(name=settings.DEFAULT_FIREWALL_NAME,
                        desc=settings.DEFAULT_FIREWALL_NAME,
                        is_default=True,
                        firewall_id=default_sec_group.id,
                        user=user,
                        user_data_center=udc,
                        deleted=False)
