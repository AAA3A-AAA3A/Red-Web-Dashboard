.. important::

    Many thanks to Neuro for the initial project and for this detailed documentation!

Reverse proxying with Nginx on Linux
====================================

Welcome to the Nginx reverse proxy guide. Note that this guide is meant only for Linux users, and that currently there are no options for Windows or Mac. These commands will not work on those OSs, so do not follow this if you are not on a Linux distribution.

Installing Nginx
----------------

1. Start off by updating your package index.

.. code-block:: none

    sudo apt update

2. Next, install the nginx package.

.. code-block:: none

    sudo apt install nginx

At this point, if you navigate to your device's IP address, you should see an Nginx welcome page.

Set up reverse proxy
--------------------

You probably don't want people visiting your domain to see that static Nginx welcome page. Now we need to configure Nginx to reverse proxy port 42356, or whichever port your webserver is running on.

1. Delete the default Nginx site.

.. code-block:: none

    sudo rm /etc/nginx/sites-enabled/default

2. Create a host configuration file for your domain:

.. code-block:: none

    sudo nano /etc/nginx/sites-available/reddash

3. Paste the following into the file, replacing ``your.domain.com`` with the domain you will be running the Dashboard on. Note that if you are running the webserver on a port other than port 42356, you will need to replace ``42356`` below with the the specified port.

.. code-block:: none

    server {
        listen 80;
        server_name your.domain.com;

        location / {
            proxy_pass http://0.0.0.0:42356;
        }
    }

.. warning::

    You should use ``localhost`` instead of ``0.0.0.0`` to make the "real" webserver port private, and use the ``--host localhost`` cli flag for starting the webserver.

4. Enable the file by creating a link from it to the sites-enabled directory.

.. code-block:: none

    sudo ln -s /etc/nginx/sites-available/reddash /etc/nginx/sites-enabled/

5. Finally, restart Nginx for the changes to take effect.

.. code-block:: none

    sudo systemctl restart nginx

Now, if you navigate to your device's IP, you should be able to see the Dashboard (if the webserver is running).
