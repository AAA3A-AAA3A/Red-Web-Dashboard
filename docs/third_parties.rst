.. Third Parties

.. role:: python(code)
    :language: python

=============
Third Parties
=============

This guide details how to add third-party cogs to Red-Web-Dashboard and create custom pages on the web Dashboard.

---------------
Getting Started
---------------

Red-Web-Dashboard allows third-party integrations, enabling cog creators to add custom pages to the Dashboard. Users just need to install and load the cogs that offer this integration on their bot.

A "Third Parties" page is present in the Dashboard's side menu, providing quick access to visible pages. Hidden pages can be accessed via links provided by the cog itself. Additionally, a "Third Parties" tab is available on each guild's page.

⚠️ Third parties are not officially part of Red-Web-Dashboard. Any information provided will be utilized by the third parties, not Red-Web-Dashboard or the cog Dashboard. For more details, refer to the `Third Parties Disclaimer <https://github.com/Cog-Creators/Red-Dashboard/blob/master/documents/Third%20Parties%20Disclaimer.md>`.

How It Works
============

If you are an end user, you can skip this section unless you want to understand how third parties function. If you are a cog creator who wants to integrate Red-Web-Dashboard with your cogs, please continue reading.

On the Red-Web-Dashboard Side
=========================

Red-Web-Dashboard adds two endpoints: ``/third-party/<cog_name>/[page]?**[params]`` and ``/dashboard/<guild_id>/third-party/<cog_name>/[page]?**[params]``. The local Dashboard cog sends the list of third parties and pages to Red-Web-Dashboard through the get_variables RPC method, which is called at regular intervals to ensure the cog and page exist.

Depending on the parameters provided by the cog creator, the code will deny requests if the used method is not one of the allowed ones (``HEAD``, ``GET``, ``OPTIONS``, ``POST``, ``PATCH``, and ``DELETE``). If ``user_id`` is a required parameter, the Dashboard will request the OAuth login of the current user. If ``guild_id`` is required, the current ``dashboard.html`` page will be displayed to allow the choice of a guild.
``user_id``, ``guild_id``, ``member_id``, ``role_id``, and ``channel_id`` are context variables, which should be integers. Currently, choice is not possible for members, roles, and channels, but these parameters could be provided manually by cogs in Discord. If parameters are required, the Dashboard will display an error in the browser.

A web request will be sent to the local cog Dashboard, which will dispatch the data correctly and get a response.

Types of Responses from Third Parties
=====================================

Third parties must return a dict to the local cog Dashboard, similar to a real RPC method.

The API endpoint supports several keys:

- ``status`` (``int``): This field is not used, but any request response should have it. Use ``0`` if the request is successful.

- ``data`` (``Dict``): The data will be returned directly as JSON, and all other fields will be ignored.

- ``notifications`` (``List[Dict[Literal["message", "category"], str]]``): A list of notifications to display to the user. Each notification is a dict with a ``category`` (``info``, ``warning``, ``error``, or ``success``) and a ``message`` (e.g., ``[{"message": "Hi!", "category": "success"}]``).

- ``web_content`` (``Dict[str, Any]``): The Flask/Django/Jinja2 template in ``source`` will be displayed in the browser, inside a third party template (consistency with the rest of the Dashboard). It can contain HTML, CSS, and JavaScript. You can use ``"standalone": True`` to make your own complete page, ``"expanded": True`` to use the template but without the guild profile, and ``"fullscreen": True`` to use the template but without the sidenav and the guild profile. All other kwargs will be passed to the template. For example: ``{"source": "Hello, {{ user_name }}!", "user_name": "Test"}``.

- ``error_code`` (``int``) associated with optional ``error_message`` (``str``): Aborts and raises an HTML error, with a custom message if provided.

- ``error_title`` (``str``) associated with optional ``error_message`` (``str``): Displays the provided message directly to the user using the ``error_message.html`` file, without the need to code a different HTML content.

- ``redirect_url`` (``str``): A URL to redirect the user to. The user will be redirected to the provided URL. Any external website will be ignored.

If content fields are not passed, the data will be returned directly as JSON.

On the Dashboard Local Cog Side
===============================

A ``DashboardRPC_ThirdParties`` handler has been added and is accessible at ``Dashboard.rpc.third_parties_handler``. A third party is linked to a ``commands.Cog`` object, which must be loaded in order to be used. The ``DashboardRPC_ThirdParties.add_third_party`` method must be used to add a cog as a third party. The page parameters are stored in ``DashboardRPC_ThirdParties.third_parties``.
The ``dashboard.rpc.thirdparties.dashboard_page`` decorator allows providing parameters for each page. All attributes of the cog class that have a ``__dashboard_params__`` attribute will be automatically added to the Dashboard when the add third party method is called. Context parameters (``user_id``/``user``, ``guild_id``/``guild``, ``member_id``/``member``, ``role_id``/``role``, ``channel_id``/``channel``) and required parameters are detected in the method parameter names.

Here are the parameters for the ``dashboard.rpc.thirdparties.dashboard_page`` decorator:

- ``name`` (``Optional[str]``): Defaults to ``None`` so that the user does not have to specify the name to access this page. The name will have the same limitations as Discord slash command names for ease of use.

- ``methods`` (``Tuple[Literal["HEAD", "GET", "OPTIONS", "POST", "PATCH", "DELETE"]]``): The web request methods allowed to call the third-party page.

- ``context_ids`` (``List[str]``): Manually specify required context IDs.

- ``required_kwargs`` (``List[str]``): Manually specify required parameters.

- ``optional_kwargs`` (``List[str]``): Manually specify optional parameters.

- ``is_owner`` (``bool``): Prevents access to the page if the user is not one of the bot owners.

- ``hidden`` (``bool``): Determines whether the page is hidden in the third parties list. Defaults to False, or True if there are required kwargs.

The ``DashboardRPC_ThirdParties.data_receive`` RPC method receives the data from Red-Web-Dashboard for the mentioned API endpoint. It checks the existence of the third party and the page. If the cog is no longer loaded, the request is refused with an error message. If a ``context_ids`` variable is provided (``user_id``, ``guild_id``, ``member_id``, ``role_id``, or ``channel_id``), the code checks if the bot has access to it and if the Discord objects actually exist. The parameters ``user``, ``guild``, ``member``, ``role``, and ``channel`` are then added.

The arguments received from Red-Web-Dashboard (and passed to cogs) are ``method`` (``Literal["HEAD", "GET", "OPTIONS", "POST", "PATCH", "DELETE"]``), ``request_url`` (``str``), ``csrf_token`` (``typing.Tuple[str, str]``), ``wtf_csrf_secret_key`` (``bytes``), ``**context_ids``, ``**required_kwargs``, ``**optional_kwargs``, ``extra_kwargs`` (``typing.Dict[str, typing.Any]``), ``data`` (``typing.Dict[typing.Literal["form", "json"], ImmutableMultiDict[str, typing.Union[typing.Any, typing.List[typing.Any]]]]``), and ``lang_code`` (`str`). Cogs should use ``**kwargs`` last, as the user (or Flask) is free to add any parameters they wish to the pages in the URL.

-----------------
What about forms?
-----------------

Forms are a crucial component of a web dashboard because they enable direct interaction with the bot, bypassing the need for Discord.

To simplify forms implementation, a ``Form`` utility has been developed. This utility, passed as a keyword argument, allows the use of ``WTForms`` fields. ``WTForms`` is a handy Python module for creating HTML5 forms with ease. This utility enables the integration of conditions that are verified on both the client and server sides (``validators``), as well as ``default`` values... For a comprehensive understanding of its capabilities, refer to the ``WTForms`` documentation (https://wtforms.readthedocs.io/). If a validator fails, ``validate_on_submit`` returns False, and the user receives a warning notification, can complete the inputs.

Another benefit of this utility is its management of a hidden ``csrf_token`` field, similar to Flask-WTF. This feature helps prevent attacks that involve one website impersonating a user, which is crucial for security.

The ``DpyObjectConverter`` validator, also passed as a keyword argument, is available to convert Discord objects from form data. It is used in the ``Form.validate_dpy_converters`` async method, which should be invoked after the ``Form.validate_on_submit`` method. This ensures the correct conversion of Discord objects and automatically handles the author and the guild.

--------------------------------------------
How to integrate third parties in your cogs?
--------------------------------------------

The cog Dashboard is capable of loading after third-party cogs when the bot is starting or simply reloaded. Upon loading, it dispatches the ``on_dashboard_cog_load```` event. This event is also manually triggered for a specific cog when that cog is loaded. This approach allows a cog to be added to Red-Web-Dashboard under any circumstances, using a single method to add all its pages.

To avoid the need for the ``commands.Cog.cog_unload```` method, the cog Dashboard employs the ``on_cog_remove event``. This event automatically removes the third party upon unloading.

For example, consider a cog named ``MyCog``, which includes the Python files ``__init__.py``, ``mycog.py``, and ``dashboard_integration.py``.

In ``__init__.py``:

.. code-block:: python

    from redbot.core.bot import Red

    from .mycog import MyCog

    async def setup(bot: Red):
        cog: MyCog = MyCog(bot)
        await bot.add_cog(cog)

In ``mycog.py``:

.. code-block:: python

    from redbot.core import commands
    from redbot.core.bot import Red

    class MyCog(DashboardIntegration, commands.Cog):  # Subclass ``DashboardIntegration``: this allows to integrate the methods in the cog class, without overloading it.
        def __init__(self, bot: Red):
            self.bot: Red = bot

        @commands.is_owner()
        @commands.command()
        async def hello(self, ctx: commands.Context, user: discord.User, *, message: str = "Hello World!"):
            await user.send(message)

In ``dashboard_integration.py``:

.. code-block:: python

    from redbot.core import commands
    from redbot.core.bot import Red
    import discord
    import typing

    def dashboard_page(*args, **kwargs):  # This decorator is required because the cog Dashboard may load after the third party when the bot is started.
        def decorator(func: typing.Callable):
            func.__dashboard_decorator_params__ = (args, kwargs)
            return func
        return decorator


    class DashboardIntegration:
        bot: Red

        @commands.Cog.listener()
        async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:  # ``on_dashboard_cog_add`` is triggered by the Dashboard cog automatically.
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)  # Add the third party to Dashboard.

        @dashboard_page(name=None, description="Send **Hello** to a user!", methods=("GET", "POST"), is_owner=True)  # Create a default page for the third party (``name=None``). It will be available at the URL ``/third-party/MyCog``.
        async def send_hello(self, user: discord.User, **kwargs) -> typing.Dict[str, typing.Any]:  # The kwarg ``user`` means that Red-Web-Dashboard will request a connection from a bot user with OAuth from Discord.
            import wtforms
            class Form(kwargs["Form"]):  # Create a WTForms form.
                def __init__(self):
                    super().__init__(prefix="send_hello_form_")
                user: wtforms.IntegerField = wtforms.IntegerField("User:", validators=[wtforms.validators.InputRequired(), kwargs["DpyObjectConverter"](discord.User)])
                message: wtforms.TextAreaField = wtforms.TextAreaField("Message:", validators=[wtforms.validators.InputRequired(), wtforms.validators.Length(max=2000)], default="Hello World!")
                submit: wtforms.SubmitField = wtforms.SubmitField("Send Hello!")

            form: Form = Form()
            if form.validate_on_submit() and await form.validate_dpy_converters():  # Check if the form is valid, run validators and retrieve the Discord objects.
                recipient = form.user.data  # Thanks to the ``DpyObjectConverter`` validator, the user object is directly retrieved.
                try:
                    await recipient.send(form.message.data)
                except discord.Forbidden:
                    return {
                        "status": 0,
                        "notifications": [{"message": f"Hello could not be sent to {recipient.display_name}!", "category": "error"}],
                    }
                return {
                    "status": 0,
                    "notifications": [{"message": f"Hello sent to {recipient.display_name} with success!", "category": "success"}],
                    "redirect_url": kwargs["request_url"],
                }

            source = "{{ form|safe }}"

            return {
                "status": 0,
                "web_content": {"source": source, "form": form},
            }

        @dashboard_page(name="guild", description="Get basic details about a __guild__!")  # Create a page nammed "guild" for the third party. It will be available at the URL ``/dashboard/<guild_id>/third-party/MyCog/guild``.
        async def guild_page(self, user: discord.User, guild: discord.Guild, **kwargs) -> typing.Dict[str, typing.Any]:  # The kwarg ``guild`` means that Red-Web-Dashboard will ask for the choice of a guild among those to which the user has access.
            return {
                "status": 0,
                "web_content": {  # Return a web content with the text variable ``title_content``.
                    "source": '<h4>You are in the guild "{{ guild.name }}" ({{ guild.id }})!</h4>',                },
            }

---------------------------------
Closing Words and Further Reading
---------------------------------

If you're reading this, it means that you've made it to the end of this guide.
Congratulations! You are now prepared with the Third Parties integrations for Red-Web-Dashboard.