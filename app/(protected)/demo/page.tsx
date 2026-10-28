import { DemoWorkspace } from "@/components/demo/DemoWorkspace";
import { PageHeader } from "@/components/layout/PageHeader";

export default function DemoPage() {
  return (
    <>
      <PageHeader
        title="Boundary Crossing Demo"
        description="Upload recorded CCTV footage, draw a restricted zone, and run person detection with ByteTrack IDs."
      />
      <DemoWorkspace />
    </>
  );
}
