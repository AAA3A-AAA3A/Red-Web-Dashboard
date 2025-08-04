.. important::

    Many thanks to Neuro for the initial project and for this detailed documentation!

Mac/Linux Installation
======================

.. attention::

   This webserver and it's accompanying cog is built for Red-DiscordBot. It will not work with other bots. If you haven’t already, install Red `here <https://docs.discord.red/en/stable/>`__.

.. warning::

   For safety reasons, do not install Red-Web-Dashboard with a `root` user. If you are unsure how to create a new user on Linux, see `DigitalOcean’s tutorial: How To Create a New Sudo-enabled User <https://www.digitalocean.com/community/tutorials/how-to-create-a-new-sudo-enabled-user-on-ubuntu-20-04-quickstart>`__.

Welcome to the Mac/Linux Installation Guide for the Red-DiscordBot Dashboard Webserver. While running the below directions, the following is assumed:
-  You are on a Mac or Linux distribution.
-  You have all pre-requisites of Red-DiscordBot installed.
-  You have an instance of Red-DiscordBot, set up and initialized.

Installing the pre-requirements
-------------------------------

This guide recommends using the same requisites that Red-DiscordBot uses. To ensure that you have the proper software already installed, consult the installation guide for your operating system `here <https://docs.discord.red/en/stable/install_guides/index.html>`__.

Creating a virtual environment
------------------------------

Just like for Red-DiscordBot, Red Dashboard requires it's own, separate virtual environment to isolate dependencies.

You have two options for creating the virtual environment, depending on how you installed Red/Python:

1. :ref:`using-venv` (available to anyone)
2. :ref:`using-pyenv-virtualenv` (only available for those who installed ``pyenv`` when installing Red)

.. _using-venv:

Using venv
~~~~~~~~~~

Red-Web-Dashboard, similar to Red-DiscordBot, requires a Python version of at least 3.8.1. For ease of use, we recommend to use the same exact Python version as you use for Red.

First, create a virtual environment using whatever Python version you use for red. For example, if Python 3.11 was installed and being used for Red:

.. prompt:: bash

   python -m venv ~/reddashenv

.. warning::

   You cannot use your Red-DiscordBot virtual environment for Red-Web-Dashboard. The two packages use different versions of the same dependencies and will conflict.

Next, enter your virtual environment with this command:

.. prompt:: bash

   source ~/reddashenv/bin/activate

.. important::

   You must activate the virtual environment with the above command every time you open a new shell to run, install or update Red-Web-Dashboard.

*You can continue to* :ref:`installing-red-web-dashboard`.

.. _using-pyenv-virtualenv:

Using pyenv virtualenv
~~~~~~~~~~~~~~~~~~~~~~

Red-Web-Dashboard, similar to Red-DiscordBot, requires a Python version of at least 3.8.1. For ease of use, we recommend to use the same exact Python version as you use for Red.

First, ensure that you are using the correct version of Python:

.. prompt:: bash

   pyenv version

Next, create a virtual environment for the Red Dashboard installation:

.. prompt:: bash

   pyenv virtualenv reddashenv

.. warning::

   You cannot use your Red-DiscordBot virtual environment for Red-Web-Dashboard. The two packages use different versions of the same dependencies and will conflict.

Finally, enter your virtual environment with this command:

.. prompt:: bash

   pyenv shell reddashenv

.. important::

   You must activate the virtual environment with the above command every time you open a new shell to run, install or update Red Dashboard. You can check out other commands like ``pyenv local`` and ``pyenv global`` if you wish to keep the virtualenv activated all the time.

*You can continue to* :ref:`installing-red-web-dashboard`.

.. _installing-red-web-dashboard:

Installing Red-Web-Dashboard
------------------------

First, make sure you are in your virtual environment that you set up earlier by running the activation command mentioned above.

Once you are inside your virtual environment, update setup packages then install:

.. prompt:: bash
   :prompts: (reddashenv) $

   python -m pip install -U pip setuptools wheel
   python -m pip install -U Red-Web-Dashboard

*You can continue to* `Installing Companion Cog <../configuration_guides/installing_companion_cog>` *or* `Automatic Startup <systemctl_startup>`.