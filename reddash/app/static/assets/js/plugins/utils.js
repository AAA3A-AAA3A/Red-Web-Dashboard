/*
 * Project: Utils
 * Description: Utils for Red-Web-Dashboard.
 * Author: AAA3A
 */

$.extend({
  sendNotification(type = "info", message, from = "top", align = "center", icon = "ni ni-bell-55", timer = 8000) {
    $.notify({ icon, message }, { type, timer, placement: { from, align } });
  },

  async postData(data = { "data": {} }, url = window.location.href) {
    try {
      var response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(csrf_token && { "X-CSRFToken": csrf_token })
        },
        body: JSON.stringify(data)
      });
      if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
      var responseData = await response.json();
      if (responseData.notifications) {
        responseData.notifications.forEach(({ type, message }) => this.sendNotification(type, message));
      }
      return responseData;
    } catch (error) {
      console.error(error);
      throw error;
    }
  }
});
