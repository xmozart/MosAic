import type { Meta, StoryObj } from "@storybook/react-vite";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";

import { SignIn } from "./SignIn";

const meta: Meta = { title: "Screens/S2 Sign in", parameters: { layout: "fullscreen" } };
export default meta;
type Story = StoryObj;

const ok = async () => ({ ok: true as const });
const wrong = async () => ({ ok: false as const, message: "That password didn't match. Try again." });
const limited = async () => ({ ok: false as const, message: "Too many attempts. Try again shortly.", retryAfter: 30 });

export const SignInDefault: Story = { render: () => <SignIn setup={false} host="mosaic.local" submit={ok} /> };
export const FirstTimeSetup: Story = { render: () => <SignIn setup host="mosaic.local" submit={ok} /> };
/** Submit any password to see the danger banner. */
export const WrongPassword: Story = { render: () => <SignIn setup={false} host="mosaic.local" submit={wrong} /> };
/** Submit any password to see the countdown. */
export const RateLimited: Story = { render: () => <SignIn setup={false} host="mosaic.local" submit={limited} /> };

export const Banners: Story = {
  render: () => (
    <div className="flex w-[560px] flex-col gap-3 p-6">
      <Banner kind="danger">That password didn't match. Try again.</Banner>
      <Banner kind="warning">2 cameras may have the wrong time.</Banner>
      <Banner kind="info" action={<Button size="sm">Open library</Button>}>
        Your footage is ready to browse and edit. Deeper analysis continues in the background.
      </Banner>
    </div>
  ),
};
