// CarStable's decisions, on plain byte images of the game's car stable (FEPlayerCarDB, speed.exe v1.3, PC layout:
// docs/cars-notes.md "Addresses for CarStable"). No game or Windows calls, so it is tested natively
// (cars/tests/stable_tests.cpp).
//
// reconcile() brings a stable loaded from an older save in line with the cars the game has now:
//  - a car of the default stable that the loaded one lacks (same VehicleKey and list bits) is added, with a copy of
//    its customisation record if it has one;
//  - a car whose VehicleKey no default record uses (a removed car) is deleted the way FEPlayerCarDB::DeleteCar does,
//    with its customisation and career records, and references to it are reset to the default car.
#pragma once
#include <cstdint>
#include <cstring>
#include <vector>

namespace cars {

constexpr int kStableSize = 0x8CC8;
constexpr int kMaxCars = 200, kMaxCustom = 75, kMaxCareer = 25;
constexpr int kCarsOfs = 0x0, kCustomOfs = 0xFA0, kCustomSize = 0x198, kCustomHandleOfs = 0x194;
constexpr int kCareerOfs = 0x8728, kCareerSize = 0x38;
constexpr uint32_t kNoCar = 0xFFFFFFFFu;
constexpr uint8_t kNoSmall = 0xFF;
constexpr uint32_t kListBits = 0xFFFF;

#pragma pack(push, 1)
struct CarRecord {
    uint32_t handle;
    uint32_t fe_key;
    uint32_t vehicle_key;
    uint32_t filter_bits;
    uint8_t customization;
    uint8_t career;
    uint16_t pad;
};
#pragma pack(pop)
static_assert(sizeof(CarRecord) == 0x14, "FECarRecord is 0x14 bytes");

class Stable {
  public:
    explicit Stable(uint8_t* p) : p_(p) {}
    CarRecord* car(int i) const { return reinterpret_cast<CarRecord*>(p_ + kCarsOfs + i * (int)sizeof(CarRecord)); }
    uint8_t* custom(int i) const { return p_ + kCustomOfs + i * kCustomSize; }
    uint8_t& custom_handle(int i) const { return custom(i)[kCustomHandleOfs]; }
    uint8_t& custom_byte(int i, int ofs) const { return custom(i)[ofs]; }
    uint8_t& career_handle(int i) const { return p_[kCareerOfs + i * kCareerSize]; }
    bool valid(int i) const { return car(i)->handle != kNoCar; }

  private:
    uint8_t* p_;
};

struct ReconcileResult {
    int added = 0;
    int dropped = 0;
    int not_added_full = 0;
    bool reset_current = false;
    int reset_quickrace = 0;
    bool guard_tripped = false;            // more cars would have been dropped than allowed: nothing was changed
    std::vector<uint32_t> not_added_keys;  // VehicleKeys of the cars that did not fit
    std::vector<uint32_t> dropped_keys;    // VehicleKeys of the dropped (or, with the guard, droppable) cars
};

constexpr int kDefaultMaxDrop = 3;

inline bool fingerprint_accepted(uint32_t saved, uint32_t current, const std::vector<uint32_t>& known) {
    if (saved == current) return true;
    for (uint32_t k : known)
        if (k == saved) return true;
    return false;
}

inline ReconcileResult reconcile(uint8_t* loaded, const uint8_t* defaults, uint32_t* current_car,
                                 uint32_t quickrace_cars[11], uint32_t default_car, int max_drop = kDefaultMaxDrop) {
    ReconcileResult r;
    Stable L(loaded), D(const_cast<uint8_t*>(defaults));

    auto key_in_defaults = [&](uint32_t vkey) {
        for (int i = 0; i < kMaxCars; i++)
            if (D.valid(i) && D.car(i)->vehicle_key == vkey) return true;
        return false;
    };
    auto removed = [&](int i) { return L.valid(i) && !key_in_defaults(L.car(i)->vehicle_key); };

    // 0. Guard: a broken database (or a second stable such as the Unlimiter's StockCarsHook) would make many cars
    //    look removed; then nothing is changed and the caller refuses the load.
    for (int i = 0; i < kMaxCars; i++)
        if (removed(i)) r.dropped_keys.push_back(L.car(i)->vehicle_key);
    if ((int)r.dropped_keys.size() > max_drop) {
        r.guard_tripped = true;
        return r;
    }

    // The car that replaces a removed current car: another car of the career (CAREER list) that stays, else the
    // default car (the game's own choice when a career starts).
    uint32_t career_replacement = default_car;
    for (int i = 0; i < kMaxCars; i++)
        if (L.valid(i) && !removed(i) && (L.car(i)->filter_bits & 2) && L.car(i)->handle != *current_car) {
            career_replacement = L.car(i)->handle;
            break;
        }

    // 1. Drop cars that no longer exist (frees slots for step 2).
    for (int i = 0; i < kMaxCars; i++) {
        if (!removed(i)) continue;
        CarRecord* c = L.car(i);
        uint32_t handle = c->handle;
        if (c->customization < kMaxCustom) L.custom_handle(c->customization) = kNoSmall;
        if (c->career < kMaxCareer) L.career_handle(c->career) = kNoSmall;
        c->handle = kNoCar;
        r.dropped++;
        if (*current_car == handle) {
            *current_car = career_replacement;
            r.reset_current = true;
        }
        for (int q = 0; q < 11; q++)
            if (quickrace_cars[q] == handle) {
                quickrace_cars[q] = default_car;
                r.reset_quickrace++;
            }
    }

    // 2. Add default cars the loaded stable lacks.
    for (int d = 0; d < kMaxCars; d++) {
        if (!D.valid(d)) continue;
        const CarRecord* want = D.car(d);
        bool present = false;
        for (int i = 0; i < kMaxCars && !present; i++)
            present = L.valid(i) && L.car(i)->vehicle_key == want->vehicle_key &&
                      (L.car(i)->filter_bits & kListBits) == (want->filter_bits & kListBits);
        if (present) continue;

        int slot = -1;
        for (int i = 0; i < kMaxCars && slot < 0; i++)
            if (!L.valid(i)) slot = i;
        int cslot = -1;
        bool needs_custom = want->customization < kMaxCustom;
        if (needs_custom)
            for (int i = 0; i < kMaxCustom && cslot < 0; i++)
                if (L.custom_handle(i) == kNoSmall) cslot = i;
        if (slot < 0 || (needs_custom && cslot < 0)) {
            r.not_added_full++;
            r.not_added_keys.push_back(want->vehicle_key);
            continue;
        }

        // A preset or bonus record keeps its name-hash handle (the game finds it by that), unless a loaded record
        // already uses it; an ordinary record's handle is its slot.
        uint32_t handle = (uint32_t)slot;
        if (want->handle != (uint32_t)d) {
            bool taken = false;
            for (int i = 0; i < kMaxCars && !taken; i++) taken = L.valid(i) && L.car(i)->handle == want->handle;
            if (!taken) handle = want->handle;
        }
        CarRecord* c = L.car(slot);
        *c = *want;
        c->handle = handle;
        c->career = kNoSmall;
        if (needs_custom) {
            std::memcpy(L.custom(cslot), D.custom(want->customization), kCustomSize);
            L.custom_handle(cslot) = (uint8_t)cslot;
            c->customization = (uint8_t)cslot;
        } else {
            c->customization = kNoSmall;
        }
        r.added++;
    }
    return r;
}

}  // namespace cars
