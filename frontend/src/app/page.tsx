import Link from "next/link";

export default function HomePage() {
  return (
    <Link
      href="/workspace/chats/new"
      aria-label="Start a new chat"
      className="fixed inset-0 block bg-cover bg-center bg-no-repeat"
      style={{ backgroundImage: "url('/main-landing.webp')" }}
    >
      <span className="sr-only">Start a new chat</span>
    </Link>
  );
}
