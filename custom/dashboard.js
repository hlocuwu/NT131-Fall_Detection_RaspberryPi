import { onAuthStateChanged, signOut } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js";
import { auth } from "/custom/firebase-app.js";

function getTheme() {
  return localStorage.getItem("theme") || "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const dark = theme === "dark";
  const icon = dark ? "🌙" : "☀️";
  const text = dark ? "Dark" : "Light";
  const iconEl = document.getElementById("themeIcon");
  const textEl = document.getElementById("themeText");
  if (iconEl) {
    iconEl.textContent = icon;
  }
  if (textEl) {
    textEl.textContent = text;
  }
}

window.toggleTheme = function toggleTheme() {
  const next = getTheme() === "light" ? "dark" : "light";
  localStorage.setItem("theme", next);
  applyTheme(next);
};

function setUserUI(user) {
  const name = user?.displayName || user?.email || "User";
  const shortName = name.trim().charAt(0).toUpperCase() || "U";
  const avatar = document.getElementById("userAvatar");
  const userLabel = document.getElementById("userLabel");

  if (avatar) {
    avatar.textContent = shortName;
    avatar.title = name;
  }
  if (userLabel) {
    userLabel.textContent = name;
  }
}

const logoutBtn = document.getElementById("logoutBtn");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    try {
      await signOut(auth);
      window.location.href = "/login";
    } catch (error) {
      console.error("Logout failed", error);
      alert("Logout failed. Please try again.");
    }
  });
}

onAuthStateChanged(auth, (user) => {
  if (!user) {
    window.location.href = "/login";
    return;
  }
  setUserUI(user);
});

applyTheme(getTheme());
