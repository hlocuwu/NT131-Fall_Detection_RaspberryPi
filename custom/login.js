import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js";
import { auth, googleProvider, isFirebaseConfigured, upsertUserProfile } from "/custom/firebase-app.js";

const signInTab = document.getElementById("signInTab");
const signUpTab = document.getElementById("signUpTab");
const loginForm = document.getElementById("loginForm");
const signInForm = document.getElementById("signInForm");
const signUpForm = document.getElementById("signUpForm");
const errorMessage = document.getElementById("errorMessage");
const successMessage = document.getElementById("successMessage");
const googleLoginBtn = document.getElementById("googleLoginBtn");

const formTitle = document.getElementById("formTitle");
const formSubtitle = document.getElementById("formSubtitle");

function showForm(mode) {
  const signInMode = mode === "signin";
  signInTab.classList.toggle("active", signInMode);
  signUpTab.classList.toggle("active", !signInMode);
  signInForm.classList.toggle("hidden", !signInMode);
  signUpForm.classList.toggle("hidden", signInMode);
  if (formTitle) {
    formTitle.textContent = signInMode ? "Welcome back" : "Create an account";
  }
  if (formSubtitle) {
    formSubtitle.textContent = signInMode
      ? "Sign in to access the monitoring dashboard"
      : "Fill in the form below to get started";
  }
  hideMessages();
}

function setLoading(btnId, loading, defaultLabel) {
  const btn = document.getElementById(btnId);
  if (!btn) { return; }
  btn.disabled = loading;
  btn.textContent = loading ? "Please wait..." : defaultLabel;
  btn.style.opacity = loading ? "0.7" : "1";
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.style.display = "block";
  successMessage.style.display = "none";
}

function showSuccess(message) {
  successMessage.textContent = message;
  successMessage.style.display = "block";
  errorMessage.style.display = "none";
}

function hideMessages() {
  errorMessage.style.display = "none";
  successMessage.style.display = "none";
}

function normalizeAuthError(error) {
  const code = error?.code || "unknown";
  const map = {
    "auth/invalid-credential": "Email hoặc mật khẩu không đúng.",
    "auth/user-not-found": "Không tìm thấy tài khoản.",
    "auth/wrong-password": "Mật khẩu không đúng.",
    "auth/email-already-in-use": "Email đã được đăng ký.",
    "auth/invalid-email": "Email không hợp lệ.",
    "auth/weak-password": "Mật khẩu quá yếu (tối thiểu 6 ký tự).",
    "auth/popup-closed-by-user": "Bạn đã đóng cửa sổ đăng nhập Google.",
    "auth/network-request-failed": "Lỗi mạng. Vui lòng kiểm tra kết nối Internet."
  };
  return map[code] || "Đăng nhập thất bại. Vui lòng thử lại.";
}

async function handleSignIn(event) {
  event.preventDefault();
  hideMessages();

  const form = new FormData(signInForm);
  const email = String(form.get("email") || "").trim();
  const password = String(form.get("password") || "");

  if (!email || !password) {
    showError("Vui lòng nhập đầy đủ email và mật khẩu.");
    return;
  }

  setLoading("signInBtn", true, "Sign In");
  try {
    const { user } = await signInWithEmailAndPassword(auth, email, password);
    await upsertUserProfile(user, { provider: "password" });
    window.location.href = "/";
  } catch (error) {
    showError(normalizeAuthError(error));
    setLoading("signInBtn", false, "Sign In");
  }
}

async function handleSignUp(event) {
  event.preventDefault();
  hideMessages();

  const form = new FormData(signUpForm);
  const fullName = String(form.get("fullName") || "").trim();
  const email = String(form.get("email") || "").trim();
  const password = String(form.get("password") || "");
  const confirmPassword = String(form.get("confirmPassword") || "");

  if (!fullName || !email || !password || !confirmPassword) {
    showError("Vui lòng điền đầy đủ thông tin đăng ký.");
    return;
  }

  if (password !== confirmPassword) {
    showError("Mật khẩu xác nhận không khớp.");
    return;
  }

  setLoading("signUpBtn", true, "Create Account");
  try {
    const { user } = await createUserWithEmailAndPassword(auth, email, password);
    await upsertUserProfile(user, { displayName: fullName, provider: "password" });
    showSuccess("Account created! Redirecting to dashboard...");
    setTimeout(() => {
      window.location.href = "/";
    }, 800);
  } catch (error) {
    showError(normalizeAuthError(error));
    setLoading("signUpBtn", false, "Create Account");
  }
}

async function handleGoogleLogin() {
  hideMessages();
  const btn = document.getElementById("googleLoginBtn");
  if (btn) { btn.disabled = true; btn.style.opacity = "0.7"; }
  try {
    const { user } = await signInWithPopup(auth, googleProvider);
    await upsertUserProfile(user, { provider: "google" });
    window.location.href = "/";
  } catch (error) {
    showError(normalizeAuthError(error));
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
  }
}

function initTheme() {
  const theme = localStorage.getItem("theme") || "light";
  document.documentElement.setAttribute("data-theme", theme);
  const dark = theme === "dark";
  document.getElementById("themeIconLogin").textContent = dark ? "🌙" : "☀️";
  document.getElementById("themeTextLogin").textContent = dark ? "Dark" : "Light";
}

window.toggleTheme = function toggleTheme() {
  const current = localStorage.getItem("theme") || "light";
  const next = current === "light" ? "dark" : "light";
  localStorage.setItem("theme", next);
  initTheme();
};

if (!isFirebaseConfigured) {
  showError("Firebase chưa được cấu hình. Hãy cập nhật file custom/firebase-config.js");
  loginForm.classList.add("hidden");
} else {
  signInTab.addEventListener("click", () => showForm("signin"));
  signUpTab.addEventListener("click", () => showForm("signup"));
  signInForm.addEventListener("submit", handleSignIn);
  signUpForm.addEventListener("submit", handleSignUp);
  googleLoginBtn.addEventListener("click", handleGoogleLogin);

  onAuthStateChanged(auth, (user) => {
    if (user) {
      window.location.href = "/";
    }
  });
}

initTheme();
showForm("signin");
