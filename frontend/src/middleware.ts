import { NextResponse, type NextRequest } from "next/server";

// UX-only guard: send visitors without a session cookie to /login.
// Real authorization is enforced by the backend on every API call.
export function middleware(req: NextRequest) {
  const hasSession = req.cookies.has("__Host-at_session") || req.cookies.has("at_session");
  if (!hasSession && !req.nextUrl.pathname.startsWith("/login")) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
