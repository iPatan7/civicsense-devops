/* Live complaint assistant.
 *
 * While the citizen types, the text is sent to /api/analyse/ and the reply is
 * shown next to the form: which department will get the complaint, how urgent
 * the engine thinks it is, and which existing complaints look like the same
 * problem.  Nothing is saved by this call - it only previews the decision the
 * server will take when the form is submitted. */
(function () {
  "use strict";

  var titleInput = document.getElementById("id_title");
  var descriptionInput = document.getElementById("id_description");
  if (!descriptionInput) { return; }

  var wardInput = document.getElementById("id_ward");
  var latitudeInput = document.getElementById("id_latitude");
  var longitudeInput = document.getElementById("id_longitude");
  var spinner = document.getElementById("assistant-spinner");
  var idle = document.getElementById("assistant-idle");
  var result = document.getElementById("assistant-result");
  var timer = null;
  var lastPayload = "";

  function csrfToken() {
    var match = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    if (match) { return match[2]; }
    var field = document.querySelector("[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  function priorityClass(label) {
    return "badge chip prio-" + String(label || "low").toLowerCase();
  }

  function render(data) {
    if (!data.ready) { return; }
    idle.classList.add("d-none");
    result.classList.remove("d-none");

    document.getElementById("assistant-category").textContent = data.category.name;
    document.getElementById("assistant-department").textContent =
      data.category.department ? "Will be sent to: " + data.category.department : "";
    document.getElementById("assistant-confidence").textContent = data.category.confidence;
    document.getElementById("assistant-confidence-bar").style.width =
      data.category.confidence + "%";
    document.getElementById("assistant-keywords").textContent =
      (data.category.keywords || []).join(", ") || "-";

    var priority = document.getElementById("assistant-priority");
    priority.className = priorityClass(data.priority.label);
    priority.textContent = data.priority.label + " (" + data.priority.score + "/100)";
    document.getElementById("assistant-sla").textContent =
      " target: " + data.priority.sla_hours + " hours";

    var reasons = document.getElementById("assistant-reasons");
    reasons.innerHTML = "";
    (data.priority.reasons || []).forEach(function (reason) {
      var item = document.createElement("li");
      item.textContent = reason;
      reasons.appendChild(item);
    });

    var box = document.getElementById("assistant-duplicates");
    var list = document.getElementById("assistant-duplicate-list");
    list.innerHTML = "";
    if (data.similar && data.similar.length) {
      box.classList.remove("d-none");
      data.similar.forEach(function (item) {
        // Titles come from other citizens, so everything is set as text, never as HTML.
        var wrapper = document.createElement("div");
        wrapper.className = "duplicate-item";

        var header = document.createElement("div");
        header.className = "d-flex justify-content-between";
        var link = document.createElement("a");
        link.textContent = item.tracking_id;
        if (typeof item.url === "string" && item.url.charAt(0) === "/" && item.url.charAt(1) !== "/") {
          link.href = item.url;
          link.target = "_blank";
          link.rel = "noopener";
        }
        var badge = document.createElement("span");
        badge.className = "badge chip " + (item.is_duplicate ? "sla-breached" : "category");
        badge.textContent = item.similarity + "% match";
        header.appendChild(link);
        header.appendChild(badge);

        var title = document.createElement("div");
        title.textContent = item.title;

        var meta = document.createElement("div");
        meta.className = "text-muted";
        var distance = item.distance_m === null ? "" : " · " + item.distance_m + " m away";
        meta.textContent = item.status + distance + " · " + item.supports + " citizen(s) reporting";

        wrapper.appendChild(header);
        wrapper.appendChild(title);
        wrapper.appendChild(meta);
        list.appendChild(wrapper);
      });
    } else {
      box.classList.add("d-none");
    }
  }

  function analyse() {
    var payload = {
      title: titleInput ? titleInput.value : "",
      description: descriptionInput.value,
      ward: wardInput ? wardInput.value : null,
      latitude: latitudeInput && latitudeInput.value ? latitudeInput.value : null,
      longitude: longitudeInput && longitudeInput.value ? longitudeInput.value : null
    };
    var serialised = JSON.stringify(payload);
    if (serialised === lastPayload) { return; }
    lastPayload = serialised;

    spinner.classList.remove("d-none");
    fetch(window.CIVIC_ANALYSE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: serialised
    })
      .then(function (response) { return response.json(); })
      .then(render)
      .catch(function () { /* the preview is optional; the form still works */ })
      .finally(function () { spinner.classList.add("d-none"); });
  }

  function schedule() {
    window.clearTimeout(timer);
    timer = window.setTimeout(analyse, 700);   // wait until typing pauses
  }

  descriptionInput.addEventListener("input", schedule);
  if (titleInput) { titleInput.addEventListener("input", schedule); }
  if (wardInput) { wardInput.addEventListener("change", analyse); }

  var locateButton = document.getElementById("locate-btn");
  if (locateButton && navigator.geolocation) {
    locateButton.addEventListener("click", function () {
      locateButton.disabled = true;
      navigator.geolocation.getCurrentPosition(function (position) {
        latitudeInput.value = position.coords.latitude.toFixed(6);
        longitudeInput.value = position.coords.longitude.toFixed(6);
        locateButton.disabled = false;
        analyse();
      }, function () {
        locateButton.disabled = false;
        locateButton.textContent = "Location not available";
      });
    });
  }
})();
