import { PageTitle, UpcomingPhase } from "@/components/ui";

export default function OrdersPage() {
  return (
    <>
      <PageTitle title="Orders" subtitle="Place, modify, cancel and track orders" />
      <UpcomingPhase phase={4} items={["Order entry (every order passes the backend risk engine)", "Pending, executed and rejected orders with status history", "Approval queue for Manual and Semi-auto modes"]} />
    </>
  );
}
