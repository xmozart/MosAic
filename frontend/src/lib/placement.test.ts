import { placementOf } from "./placement";

it("a split project on a local disk is stored separately, not on a NAS", () => {
  expect(placementOf({ placement: "in_folder", fs_class: "local" })).toBe("in_folder");
  expect(placementOf({ placement: "split", fs_class: "network" })).toBe("split_nas");
  expect(placementOf({ placement: "split", fs_class: "cloud_synced" })).toBe("split_icloud");
  expect(placementOf({ placement: "split", fs_class: "local" })).toBe("separate");
  expect(placementOf({ placement: "external", fs_class: "read_only" })).toBe("separate");
});
