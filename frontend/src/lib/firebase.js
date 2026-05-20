import { initializeApp } from 'firebase/app'
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut as fbSignOut,
  onAuthStateChanged,
} from 'firebase/auth'

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

export const app = initializeApp(firebaseConfig)
export const auth = getAuth(app)

const provider = new GoogleAuthProvider()
// Restrict to the company Workspace domain
provider.setCustomParameters({ hd: 'ascotwm.com', prompt: 'select_account' })

export async function signInWithGoogle() {
  const result = await signInWithPopup(auth, provider)
  const email = result.user.email || ''
  if (!email.endsWith('@ascotwm.com')) {
    await fbSignOut(auth)
    throw new Error('Only @ascotwm.com accounts are permitted.')
  }
  return result.user
}

export async function signOut() {
  await fbSignOut(auth)
}

export function onAuthChange(callback) {
  return onAuthStateChanged(auth, callback)
}

export async function getIdToken() {
  const user = auth.currentUser
  if (!user) return null
  return user.getIdToken()
}
