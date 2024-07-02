import vagrant
from fabric.api import env, execute, task, run
from fabric.api import settings, run

@task
def mytask():
    import traceback; traceback.print_stack()
    run('echo $USER | tee log')

v = vagrant.Vagrant()
print(v)
v.up()
with settings(host_string=v.user_hostname_port(), key_filename=v.keyfile(), disable_known_hosts=True, warn_only = True):
    output = run('timeout 60 echo hi')
    print("vagrant output:", output)
