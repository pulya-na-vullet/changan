(function () {
  /**
   * Тот же webhook, что eurocubes.html на fhk-designs.ru:
   * GET query → лист «Заявки».
   */
  var GOOGLE_SHEET_URL =
    "https://script.google.com/macros/s/AKfycbxOqN9tHBz587AD47Q7L05aIIz3HlKlncoGg-v40GfLIrr6WyDn3CWZbzTQ9QDRTIe0/exec";

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

  function submitParams(form) {
    var name = ((form.elements.name && form.elements.name.value) || "").trim();
    var phone = ((form.elements.phone && form.elements.phone.value) || "").replace(/\D/g, "");
    var params = new URLSearchParams();
    params.append(
      "timestamp",
      new Date().toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })
    );
    params.append("name", name);
    params.append("phone", phone);
    params.append("message", orderMessage(form));
    params.append("source", pageName());
    return params;
  }

  function submitOrder(form) {
    return fetch(GOOGLE_SHEET_URL + "?" + submitParams(form).toString(), {
      method: "GET",
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
