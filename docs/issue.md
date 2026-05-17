React does not recognize the `autoSaveId` prop on a DOM element. If you intentionally want it to appear in the DOM as a custom attribute, spell it as lowercase `autosaveid` instead. If you accidentally passed it from a parent component, remove it from the DOM element.
src/components/ui/resizable.tsx (14:5) @ ResizablePanelGroup


  12 | }: React.ComponentProps<typeof ResizablePrimitive.Group>) {
  13 |   return (
> 14 |     <ResizablePrimitive.Group
     |     ^
  15 |       data-slot="resizable-panel-group"
  16 |       className={cn(
  17 |         "flex h-full w-full data-[panel-group-direction=vertical]:flex-col",
Call Stack
21

Show 18 ignore-listed frame(s)
div
<anonymous>
ResizablePanelGroup
src/components/ui/resizable.tsx (14:5)
VaultPage
src/app/workspace/vault/page.tsx (536:25)
Show less
