(function () {
  /**
   * Webhook еврокубов / этой таблицы (URL заканчивается на /exec).
   * Лист: https://docs.google.com/spreadsheets/d/1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw/edit?usp=sharing
   * Колонки как eurocubes.html: дата, имя, телефон, текст заказа, страница, статус.
   */
  var QUICKBAR_ORDERS_URL = "";
  var SHEET_ID = "1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function statusEl(form) {
    return form.querySelector("[data-order-status]");
  }

  function setStatus(form, kind, text) {
    var node = statusEl(form);
    if (!node) {
      return;
    }
    node.hidden = !text;
    node.className = "order-status" + (kind ? " " + kind : "");
    node.textContent = text || "";
  }

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function formatDate() {
    var d = new Date();
    return (
      pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear() +
      ", " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds())
    );
  }

  function pageName() {
    var file = (location.pathname.split("/").pop() || "").trim();
    return file || "quickbar.html";
  }

  function orderMessage(form) {
    var city = (form.elements.city && form.elements.city.value) || "";
    var car = (form.elements.car && form.elements.car.value) || "";
    var comment = (form.elements.comment && form.elements.comment.value) || "";
    var parts = [
      "Заказ QuickBar: установка 5 000₽.",
      city ? "Город: " + city + "." : "",
      car ? "Авто: " + car + "." : "",
      comment ? "Комментарий: " + comment : ""
    ];
    return parts.filter(Boolean).join(" ");
  }

  function payload(form) {
    var name = (form.elements.name && form.elements.name.value) || "";
    var phone = (form.elements.phone && form.elements.phone.value) || "";
    var message = orderMessage(form);
    var page = pageName();
    var date = formatDate();
    var data = new FormData();
    data.set("date", date);
    data.set("timestamp", date);
    data.set("name", name);
    data.set("phone", phone);
    data.set("message", message);
    data.set("comment", message);
    data.set("page", page);
    data.set("source", page);
    data.set("Имя", name);
    data.set("Телефон", phone);
    data.set("Комментарий", message);
    data.set("Источник", page);
    return { form: data, json: {
      date: date,
      name: name,
      phone: phone,
      message: message,
      page: page,
      sheet: SHEET_ID
    }};
  }

  function submitOrder(form) {
    var url = QUICKBAR_ORDERS_URL.trim();
    var packed = payload(form);
    if (!url) {
      return Promise.reject(new Error("no-webhook"));
    }
    return fetch(url, {
      method: "POST",
      body: packed.form,
      mode: "no-cors"
    });
  }

  ready(function () {
    document.querySelectorAll("[data-order-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var btn = form.querySelector("[type=submit]");
        setStatus(form, "", "Отправляем заявку…");
        if (btn) {
          btn.disabled = true;
        }
        submitOrder(form)
          .then(function () {
            form.reset();
            setStatus(
              form,
              "ok",
              "Заявка ушла. Перезвоним, согласуем удобное время установки."
            );
          })
          .catch(function () {
            setStatus(
              form,
              "err",
              "Не отправилось. Напишите в ИТ-Мастерскую или позвоните — заявку примем вручную."
            );
          })
          .then(function () {
            if (btn) {
              btn.disabled = false;
            }
          });
      });
    });
  });
})();
