import { redirect } from "next/navigation";

export default async function DreamyThreadRedirect({
  params,
}: {
  params: Promise<{ thread_id: string }>;
}) {
  const { thread_id } = await params;
  redirect(`/workspace/chats/${thread_id}`);
}
