import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listVehicles: vi.fn(),
  listProximityEvents: vi.fn(),
}));

import { listProximityEvents, listVehicles } from "@/api";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import VehiclesView from "@/views/VehiclesView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

const mockedVehicles = vi.mocked(listVehicles);
const mockedEvents = vi.mocked(listProximityEvents);

const vehicleA = {
  id: "vvvvvvvv-1111-2222-3333-444455556666",
  camera_id: "aaaaaaaa-1111-2222-3333-444455556666",
  camera_name: "Driveway",
  description: "Blue Honda Civic",
  outline_points: [
    [0.2, 0.3],
    [0.6, 0.3],
    [0.6, 0.7],
  ],
  has_reference_frame: true,
  estimated_length_feet: 15,
  distance_threshold_feet: 6,
  enabled: true,
  updated_at: "2026-07-20T12:00:00Z",
};

const vehicleB = {
  id: "wwwwwwww-1111-2222-3333-444455556666",
  camera_id: "bbbbbbbb-1111-2222-3333-444455556666",
  camera_name: "Garage",
  description: "Work van",
  outline_points: [],
  has_reference_frame: false,
  estimated_length_feet: 20,
  distance_threshold_feet: 8,
  enabled: false,
  updated_at: "2026-07-20T12:00:00Z",
};

const event1 = {
  id: "e1111111-1111-2222-3333-444455556666",
  clip_id: "c1111111-1111-2222-3333-444455556666",
  distance_feet: 3.4,
  error_margin_feet: 1.2,
  occurred_at: "2026-07-24T10:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountView(isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  return mount(VehiclesView, { global: mountGlobal(pinia, makeRouter()) });
}

describe("VehiclesView loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedVehicles.mockReturnValue(new Promise(() => {}));
    const wrapper = mountView();
    expect(wrapper.find('[data-testid="vehicles-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails, and retry reloads", async () => {
    mockedVehicles.mockRejectedValueOnce(new ApiError(500, "Server exploded"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="vehicles-load-error"]').exists()).toBe(true);

    mockedVehicles.mockResolvedValueOnce([]);
    await wrapper.find('[data-testid="retry-vehicles"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="vehicles-load-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="vehicles-empty"]').exists()).toBe(true);
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedVehicles.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="vehicles-load-error"]').text()).toContain(
      "Couldn't load vehicles",
    );
  });

  it("shows an empty state with an admin CTA when nothing is configured", async () => {
    mockedVehicles.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="vehicles-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="go-vehicle-settings-empty"]').exists()).toBe(true);
  });

  it("hides admin shortcuts for a non-admin", async () => {
    mockedVehicles.mockResolvedValue([]);
    const wrapper = mountView(false);
    await flushPromises();
    expect(wrapper.find('[data-testid="go-vehicle-settings"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="go-vehicle-settings-empty"]').exists()).toBe(false);
  });

  it("links an admin to Settings > Vehicles from the empty state", async () => {
    mockedVehicles.mockResolvedValue([]);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(VehiclesView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="go-vehicle-settings-empty"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "vehicles" } });
  });

  it("links an admin to Settings > Vehicles from the header", async () => {
    mockedVehicles.mockResolvedValue([]);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(VehiclesView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="go-vehicle-settings"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "vehicles" } });
  });
});

describe("VehiclesView populated", () => {
  it("renders camera name, description, and active/paused status", async () => {
    mockedVehicles.mockResolvedValue([vehicleA, vehicleB]);
    mockedEvents.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();

    const cardA = wrapper.find(`[data-testid="vehicle-card-${vehicleA.camera_id}"]`);
    expect(cardA.text()).toContain("Driveway");
    expect(cardA.text()).toContain("Blue Honda Civic");
    expect(cardA.text()).toContain("Active");
    expect(cardA.text()).toContain("15 ft");
    expect(cardA.text()).toContain("6 ft");

    const cardB = wrapper.find(`[data-testid="vehicle-card-${vehicleB.camera_id}"]`);
    expect(cardB.text()).toContain("Paused");
  });

  it("shows the reference frame and outline when captured, and omits it when not", async () => {
    mockedVehicles.mockResolvedValue([vehicleA, vehicleB]);
    mockedEvents.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();

    const cardA = wrapper.find(`[data-testid="vehicle-card-${vehicleA.camera_id}"]`);
    expect(cardA.find("img").exists()).toBe(true);
    expect(cardA.find("polygon").attributes("points")).toBe("20,30 60,30 60,70");

    const cardB = wrapper.find(`[data-testid="vehicle-card-${vehicleB.camera_id}"]`);
    expect(cardB.find("img").exists()).toBe(false);
  });

  it("shows a per-vehicle loading skeleton while its events are still fetching", async () => {
    mockedVehicles.mockResolvedValue([vehicleA]);
    mockedEvents.mockReturnValue(new Promise(() => {}));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="events-loading-${vehicleA.camera_id}"]`).exists()).toBe(
      true,
    );
  });

  it("loads each vehicle's recent events independently", async () => {
    mockedVehicles.mockResolvedValue([vehicleA, vehicleB]);
    mockedEvents.mockImplementation((cameraId) =>
      cameraId === vehicleA.camera_id ? Promise.resolve([event1]) : Promise.resolve([]),
    );
    const wrapper = mountView();
    await flushPromises();

    expect(mockedEvents).toHaveBeenCalledWith(vehicleA.camera_id);
    expect(mockedEvents).toHaveBeenCalledWith(vehicleB.camera_id);

    const listA = wrapper.find(`[data-testid="event-list-${vehicleA.camera_id}"]`);
    expect(listA.text()).toContain("3.4 ft");
    expect(listA.text()).toContain("±1.2 ft");

    expect(wrapper.find(`[data-testid="events-empty-${vehicleB.camera_id}"]`).exists()).toBe(
      true,
    );
  });

  it("caps the recent events list at 5 and shows the most recent first, as returned", async () => {
    mockedVehicles.mockResolvedValue([vehicleA]);
    const many = Array.from({ length: 8 }, (_, i) => ({
      ...event1,
      id: `event-${i}`,
      distance_feet: i,
    }));
    mockedEvents.mockResolvedValue(many);
    const wrapper = mountView();
    await flushPromises();
    const items = wrapper.find(`[data-testid="event-list-${vehicleA.camera_id}"]`).findAll("li");
    expect(items).toHaveLength(5);
  });

  it("shows a per-vehicle error when its events fail to load", async () => {
    mockedVehicles.mockResolvedValue([vehicleA]);
    mockedEvents.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="events-error-${vehicleA.camera_id}"]`).text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic per-vehicle events error for non-API failures", async () => {
    mockedVehicles.mockResolvedValue([vehicleA]);
    mockedEvents.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="events-error-${vehicleA.camera_id}"]`).text()).toBe(
      "Could not load recent activity.",
    );
  });

  it("navigates to the Library pre-filtered by camera", async () => {
    mockedVehicles.mockResolvedValue([vehicleA]);
    mockedEvents.mockResolvedValue([]);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(VehiclesView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find(`[data-testid="view-clips-${vehicleA.camera_id}"]`).trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({
      name: "library",
      query: { camera_id: vehicleA.camera_id },
    });
  });
});
