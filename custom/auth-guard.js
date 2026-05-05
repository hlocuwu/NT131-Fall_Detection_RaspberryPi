import { onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js";
import { auth, isFirebaseConfigured } from "/custom/firebase-app.js";

if (!isFirebaseConfigured) {
  const message = "Firebase is not configured. Update custom/firebase-config.js first.";
  console.error(message);
  alert(message);
  window.location.href = "/login";
} else {
  onAuthStateChanged(auth, (user) => {
    if (!user) {
      window.location.href = "/login";
    }
  });
}
