#!/bin/python3
import subprocess
import datetime
import time
import sys, os
import traceback
import json
import copy
import yaml
import re

lockfile = "/tmp/autoscaling_lock"
queues_conf_file = "/opt/oci-hpc/conf/queues.conf"
idle_time = 600
script_path = '/opt/oci-hpc/bin'


def israckaware():
    rackware = False
    if os.path.isfile("/opt/oci-hpc/conf/variables.tf"):
        variablefile = open("/opt/oci-hpc/conf/variables.tf", 'r')
        for line in variablefile:
            if "\"rack_aware\"" in line and ("true" in line or "True" in line or "yes" in line or "Yes" in line):
                rackware = True
                break
    return rackware


def getTopology(clusterName):
    out = subprocess.Popen(['scontrol', 'show', 'topology', clusterName],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    stdout, stderr = out.communicate()
    for item in stdout.strip().split():
        if item.startswith("Nodes="):
            nodes_condensed = item.split("Nodes=")[1]
            out2 = subprocess.Popen(['scontrol', 'show', 'hostname', nodes_condensed],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            stdout2, stderr2 = out2.communicate()
            return stdout2.strip().split()
    return []


def getJobs():
    out = subprocess.Popen(
        ['squeue', '-r', '-O', 'STATE,JOBID,FEATURE:100,NUMNODES,Partition,UserName,Dependency'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    stdout, stderr = out.communicate()
    return stdout.split("\n")[1:]


def getClusters():
    out = subprocess.Popen(['sinfo', '-hN', '-o', '\"%T %E %D %N\"'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    stdout, stderr = out.communicate()
    return stdout.split("\n")


def getNodeDetails(node):
    out = subprocess.Popen(['sinfo', '-h', '-n', node, '-o', '"%f %R"'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    stdout, stderr = out.communicate()
    for pot_output in stdout.split("\n"):
        if not "(null)" in pot_output and pot_output.strip() != '':
            output = pot_output
            if output[0] == '"':
                output = output[1:]
            if output[-1] == '"':
                output = output[:-1]
        else:
            continue
    return output


def getIdleTime(node):
    out = subprocess.Popen(["sacct -X -n -S 01/01/01 -N " + node + " -o End | tail -n 1"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True, universal_newlines=True)
    stdout, stderr = out.communicate()
    last_end_time = None
    try:
        last_end_time = datetime.datetime.strptime(stdout.strip(), "%Y-%m-%dT%H:%M:%S")
    except:
        pass
    out = subprocess.Popen(["scontrol show node " + node + " | grep SlurmdStartTime | awk '{print $2}'"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True, universal_newlines=True)
    stdout, stderr = out.communicate()
    try:
        cluster_start_time = datetime.datetime.strptime(
            stdout.split("\n")[0].split("=")[1], "%Y-%m-%dT%H:%M:%S")
    except:
        cluster_start_time = datetime.datetime.now() - datetime.timedelta(hours=24)
    if last_end_time is None:
        right_time = cluster_start_time
    else:
        right_time = max([cluster_start_time, last_end_time])
    return (datetime.datetime.now() - right_time).total_seconds()


def getQueueConf(queue_file):
    with open(queue_file) as file:
        try:
            data = yaml.load(file, Loader=yaml.FullLoader)
        except:
            data = yaml.load(file)
        return data["queues"]


def getQueue(config, queue_name):
    for queue in config:
        if queue["name"] == queue_name:
            return queue
    return None


def getDefaultsConfig(config, queue_name):
    for partition in config:
        if queue_name == partition["name"]:
            for instance_type in partition["instance_types"]:
                if "default" in instance_type.keys():
                    if instance_type["default"]:
                        return {"queue": partition["name"], "instance_type": instance_type["name"],
                                "shape": instance_type["shape"], "cluster_network": instance_type["cluster_network"],
                                "instance_keyword": instance_type["instance_keyword"]}
            if len(partition["instance_types"]) > 0:
                instance_type = partition["instance_types"][0]
                return {"queue": partition["name"], "instance_type": instance_type["name"],
                        "shape": instance_type["shape"], "cluster_network": instance_type["cluster_network"],
                        "instance_keyword": instance_type["instance_keyword"]}
    return None


def getJobConfig(config, queue_name, instance_type_name):
    for partition in config:
        if queue_name == partition["name"]:
            for instance_type in partition["instance_types"]:
                if instance_type_name == instance_type["name"]:
                    return {"queue": partition["name"], "instance_type": instance_type["name"],
                            "shape": instance_type["shape"], "cluster_network": instance_type["cluster_network"],
                            "instance_keyword": instance_type["instance_keyword"]}
    return None


def getQueueLimits(config, queue_name, instance_type_name):
    for partition in config:
        if queue_name == partition["name"]:
            for instance_type in partition["instance_types"]:
                if instance_type_name == instance_type["name"]:
                    return {"max_number_nodes": int(instance_type["max_number_nodes"]),
                            "max_cluster_size": int(instance_type["max_cluster_size"]),
                            "max_cluster_count": int(instance_type["max_cluster_count"])}
    return {"max_number_nodes": 0, "max_cluster_size": 0, "max_cluster_count": 0}


def getInstanceType(config, queue_name, instance_keyword):
    for partition in config:
        if queue_name == partition["name"]:
            for instance_type in partition["instance_types"]:
                if instance_keyword == instance_type["instance_keyword"]:
                    return instance_type["name"]
    return None


def isPermanent(config, queue_name, instance_type_name):
    for partition in config:
        if queue_name == partition["name"]:
            for instance_type in partition["instance_types"]:
                if instance_type_name == instance_type["name"]:
                    return instance_type["permanent"]
    return None


def getClusterName(node):
    out = subprocess.Popen(['scontrol', 'show', 'topology', node],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    stdout, stderr = out.communicate()
    clusterName = None
    try:
        if len(stdout.split('\n')) > 2:
            for output in stdout.split('\n')[:-1]:
                if "Switches=" in output:
                    clusterName = output.split()[0].split('SwitchName=')[1]
                    break
                elif "SwitchName=inactive-" in output:
                    continue
                else:
                    clusterName = output.split()[0].split('SwitchName=')[1]
        elif len(stdout.split('\n')) == 2:
            clusterName = stdout.split('\n')[0].split()[0].split('SwitchName=')[1]
        if clusterName.startswith("inactive-"):
            return "NOCLUSTERFOUND"
    except:
        return "NOCLUSTERFOUND"
    return clusterName


def getstatus_slurm():
    cluster_to_build = []
    clusters_data = {}
    current_nodes = {}
    building_nodes = {}
    cluster_building = []
    cluster_destroying = []
    used_index = {}

    for line in getJobs():
        if len(line.split()) > 3:
            new_line = re.split(r"\s{1,}", line)
            if new_line[0] == 'PENDING' and ('null' in new_line[6] or len(new_line[6]) == 0):
                queue = new_line[4]
                user = new_line[5]
                features = new_line[2].split('&')
                instanceType = None
                possible_types = [inst_type["name"]
                                  for inst_type in getQueue(config, queue)["instance_types"]]
                default_config = getDefaultsConfig(config, queue)
                if instanceType is None:
                    instanceType = default_config["instance_type"]
                    for feature in features:
                        if feature in possible_types:
                            instanceType = feature
                            break
                nodes = int(new_line[3])
                jobID = int(new_line[1])
                cluster_to_build.append([nodes, instanceType, queue, jobID, user])

    for line in getClusters():
        if len(line.split()) == 0:
            break
        old_nodes = line.split()[-1].split(',')
        broken = False
        nodes = []
        for node in old_nodes:
            if broken:
                if ']' in node:
                    broken = False
                    nodes.append(currentNode + ',' + node)
                else:
                    currentNode = currentNode + ',' + node
            elif '[' in node and not ']' in node:
                broken = True
                currentNode = node
            else:
                nodes.append(node)
        for node in nodes:
            if node.endswith('"'):
                node = node[:-1]
            if node.startswith('"'):
                node = node[1:]
            details = getNodeDetails(node).split(' ')
            features = details[0].split(',')
            queue = details[-1]
            clustername = getClusterName(node)
            if clustername is None:
                continue
            instanceType = features[-1]
            if queue in current_nodes:
                current_nodes[queue][instanceType] = current_nodes[queue].get(
                    instanceType, 0) + 1
            else:
                current_nodes[queue] = {instanceType: 1}
            if clustername not in clusters_data:
                clusters_data[clustername] = {"nodes": [], "min_idle": None,
                                              "running": False, "queue": queue,
                                              "instance_type": instanceType}
            clusters_data[clustername]["nodes"].append(node)
            state = line.split()[0].strip('"')
            if state in ['allocated', 'mixed']:
                clusters_data[clustername]["running"] = True
            else:
                node_idle = getIdleTime(node)
                if clusters_data[clustername]["min_idle"] is None or node_idle < clusters_data[clustername]["min_idle"]:
                    clusters_data[clustername]["min_idle"] = node_idle

    for clusterName in os.listdir(clusters_path):
        if len(clusterName.split('-')) < 3:
            continue
        instance_keyword = '-'.join(clusterName.split('-')[2:])
        clusterNumber = int(clusterName.split('-')[1])
        queue = clusterName.split('-')[0]
        instanceType = getInstanceType(config, queue, instance_keyword)
        if queue not in used_index:
            used_index[queue] = {}
        if instanceType not in used_index[queue]:
            used_index[queue][instanceType] = []
        used_index[queue][instanceType].append(clusterNumber)
        if os.path.isfile(os.path.join(clusters_path, clusterName, 'currently_building')):
            with open(os.path.join(clusters_path, clusterName, 'currently_building'), 'r') as f:
                parts = f.read().strip().split()
                if len(parts) >= 3:
                    try:
                        nodes = int(parts[0])
                        instance_type = parts[1]
                        queue_name = parts[2]
                        cluster_building.append([nodes, instance_type, queue_name])
                        if queue_name in building_nodes:
                            building_nodes[queue_name][instance_type] = building_nodes[queue_name].get(
                                instance_type, 0) + nodes
                        else:
                            building_nodes[queue_name] = {instance_type: nodes}
                    except:
                        pass
        if os.path.isfile(os.path.join(clusters_path, clusterName, 'currently_destroying')):
            cluster_destroying.append(clusterName)

    cluster_to_destroy = []
    for clustername, info in clusters_data.items():
        if clustername == "NOCLUSTERFOUND":
            continue
        if info["running"]:
            continue
        if isPermanent(config, info["queue"], info["instance_type"]):
            continue
        if info["min_idle"] is None:
            continue
        if info["min_idle"] >= idle_time:
            cluster_to_destroy.append([clustername])
        else:
            print(f"{clustername}[{','.join(info['nodes'])}] is too young to die : {int(info['min_idle'])} sec")

    nodes_to_destroy = {}
    return cluster_to_build, cluster_to_destroy, nodes_to_destroy, cluster_building, cluster_destroying, used_index, current_nodes, building_nodes


def getAutoscaling():
    out = subprocess.Popen(
        ["cat /etc/ansible/hosts | grep 'autoscaling =' | awk -F  '= ' '{print $2}'"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True, universal_newlines=True)
    stdout, stderr = out.communicate()
    output = stdout.split("\n")
    autoscaling_value = False
    for i in range(0, len(output) - 1):
        autoscaling_value = output[i]
    return autoscaling_value


autoscaling = getAutoscaling()

if autoscaling == "true":
    if os.path.isfile(lockfile):
        print("Lockfile " + lockfile + " is present, exiting")
        exit()
    open(lockfile, 'w').close()
    try:
        path = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[0])))
        clusters_path = os.path.join(path, 'clusters')
        config = getQueueConf(queues_conf_file)
        cluster_to_build, cluster_to_destroy, nodes_to_destroy, cluster_building, cluster_destroying, used_index, current_nodes, building_nodes = getstatus_slurm()
        print(time.strftime("%Y-%m-%d %H:%M:%S"))
        print(cluster_to_build, 'cluster_to_build')
        print(cluster_to_destroy, 'cluster_to_destroy')
        print(nodes_to_destroy, 'nodes_to_destroy')
        print(cluster_building, 'cluster_building')
        print(cluster_destroying, 'cluster_destroying')
        print(current_nodes, 'current_nodes')
        print(building_nodes, 'building_nodes')
        for i in cluster_building:
            for j in cluster_to_build:
                if i[0] == j[0] and i[1] == j[1] and i[2] == j[2]:
                    cluster_to_build.remove(j)
                    break
        for cluster in cluster_to_destroy:
            cluster_name = cluster[0]
            print("Deleting cluster " + cluster_name)
            subprocess.Popen([script_path + '/delete_cluster.sh', cluster_name])
            time.sleep(5)
        for index, cluster in enumerate(cluster_to_build):
            nodes = cluster[0]
            instance_type = cluster[1]
            queue = cluster[2]
            jobID = str(cluster[3])
            user = str(cluster[4])
            jobconfig = getJobConfig(config, queue, instance_type)
            limits = getQueueLimits(config, queue, instance_type)
            try:
                clusterCount = len(used_index[queue][instance_type])
            except:
                clusterCount = 0
            if clusterCount >= limits["max_cluster_count"]:
                print("This would go over the number of running clusters, you have reached the max number of clusters")
                continue
            nextIndex = None
            if clusterCount == 0:
                if queue in used_index:
                    used_index[queue][instance_type] = [1]
                else:
                    used_index[queue] = {instance_type: [1]}
                nextIndex = 1
            else:
                for i in range(1, 10000):
                    if i not in used_index[queue][instance_type]:
                        nextIndex = i
                        used_index[queue][instance_type].append(i)
                        break
            clusterName = queue + '-' + str(nextIndex) + '-' + \
                jobconfig["instance_keyword"]
            if queue not in current_nodes:
                current_nodes[queue] = {instance_type: 0}
            else:
                if instance_type not in current_nodes[queue]:
                    current_nodes[queue][instance_type] = 0
            if queue not in building_nodes:
                building_nodes[queue] = {instance_type: 0}
            else:
                if instance_type not in building_nodes[queue]:
                    building_nodes[queue][instance_type] = 0
            if nodes > limits["max_cluster_size"]:
                print("Cluster " + clusterName +
                      " won't be created, it would go over the total number of nodes per cluster limit")
            elif current_nodes[queue][instance_type] + building_nodes[queue][instance_type] + nodes > limits["max_number_nodes"]:
                print("Cluster " + clusterName +
                      " won't be created, it would go over the total number of nodes limit")
            else:
                current_nodes[queue][instance_type] += nodes
                clusterCount += 1
                print("Creating cluster " + clusterName +
                      " with " + str(nodes) + " nodes")
                subprocess.Popen([script_path + '/create_cluster.sh', str(nodes),
                                 clusterName, instance_type, queue, jobID, user])
                time.sleep(5)
    except Exception:
        traceback.print_exc()
    os.remove(lockfile)
else:
    print("Autoscaling is false")
    exit()
