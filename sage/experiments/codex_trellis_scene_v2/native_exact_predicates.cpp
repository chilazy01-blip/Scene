#include <cmath>
#include <cstddef>
#include <vector>

// Exact signs for determinants of finite IEEE-754 doubles.  The implementation
// uses error-free transforms (Dekker products and Knuth sums), accumulating the
// resulting non-overlapping floating-point expansions from low to high order.
// It deliberately has no CGAL/GMP dependency so the capability can be built on
// the production host and independently hashed/probed.

namespace {

using Expansion = std::vector<double>;
constexpr double kSplitter = 134217729.0;  // 2^27 + 1 for binary64.

inline void two_sum(double a, double b, double &x, double &y) {
    x = a + b;
    const double b_virtual = x - a;
    const double a_virtual = x - b_virtual;
    const double b_roundoff = b - b_virtual;
    const double a_roundoff = a - a_virtual;
    y = a_roundoff + b_roundoff;
}

inline void two_diff(double a, double b, double &x, double &y) {
    x = a - b;
    const double b_virtual = a - x;
    const double a_virtual = x + b_virtual;
    const double b_roundoff = b_virtual - b;
    const double a_roundoff = a - a_virtual;
    y = a_roundoff + b_roundoff;
}

inline void split(double value, double &high, double &low) {
    const double product = kSplitter * value;
    const double big = product - value;
    high = product - big;
    low = value - high;
}

inline void two_product(double a, double b, double &x, double &y) {
    x = a * b;
    double a_high, a_low, b_high, b_low;
    split(a, a_high, a_low);
    split(b, b_high, b_low);
    const double error1 = x - a_high * b_high;
    const double error2 = error1 - a_low * b_high;
    const double error3 = error2 - a_high * b_low;
    y = a_low * b_low - error3;
}

Expansion grow(const Expansion &input, double value) {
    Expansion output;
    output.reserve(input.size() + 1);
    double accumulator = value;
    for (double component : input) {
        double sum, roundoff;
        two_sum(accumulator, component, sum, roundoff);
        if (roundoff != 0.0) output.push_back(roundoff);
        accumulator = sum;
    }
    if (accumulator != 0.0 || output.empty()) output.push_back(accumulator);
    return output;
}

Expansion add(const Expansion &first, const Expansion &second) {
    Expansion result = first;
    for (double component : second) result = grow(result, component);
    return result;
}

Expansion negate(Expansion value) {
    for (double &component : value) component = -component;
    return value;
}

Expansion difference(double a, double b) {
    double value, roundoff;
    two_diff(a, b, value, roundoff);
    Expansion result;
    if (roundoff != 0.0) result.push_back(roundoff);
    if (value != 0.0 || result.empty()) result.push_back(value);
    return result;
}

Expansion multiply(const Expansion &first, const Expansion &second) {
    Expansion result{0.0};
    for (double a : first) {
        for (double b : second) {
            double product, roundoff;
            two_product(a, b, product, roundoff);
            if (roundoff != 0.0) result = grow(result, roundoff);
            if (product != 0.0) result = grow(result, product);
        }
    }
    return result;
}

int sign(const Expansion &value) {
    for (auto iterator = value.rbegin(); iterator != value.rend(); ++iterator) {
        if (*iterator > 0.0) return 1;
        if (*iterator < 0.0) return -1;
    }
    return 0;
}

bool valid(const double *values, std::size_t count) {
    // Dekker splitting must not overflow.  Scene coordinates are normally
    // below 10^3 m; the broad bound also makes unsupported inputs explicit.
    constexpr double kMaximumMagnitude = 1.0e100;
    for (std::size_t index = 0; index < count; ++index) {
        if (!std::isfinite(values[index]) ||
            std::fabs(values[index]) > kMaximumMagnitude) return false;
    }
    return true;
}

}  // namespace

extern "C" int scene_v2_orient2d(const double *a, const double *b, const double *c) {
    if (!valid(a, 2) || !valid(b, 2) || !valid(c, 2)) return 2;
    const Expansion acx = difference(a[0], c[0]);
    const Expansion bcx = difference(b[0], c[0]);
    const Expansion acy = difference(a[1], c[1]);
    const Expansion bcy = difference(b[1], c[1]);
    return sign(add(multiply(acx, bcy), negate(multiply(acy, bcx))));
}

extern "C" int scene_v2_orient3d(
    const double *a, const double *b, const double *c, const double *d) {
    if (!valid(a, 3) || !valid(b, 3) || !valid(c, 3) || !valid(d, 3)) return 2;
    const Expansion adx = difference(a[0], d[0]);
    const Expansion ady = difference(a[1], d[1]);
    const Expansion adz = difference(a[2], d[2]);
    const Expansion bdx = difference(b[0], d[0]);
    const Expansion bdy = difference(b[1], d[1]);
    const Expansion bdz = difference(b[2], d[2]);
    const Expansion cdx = difference(c[0], d[0]);
    const Expansion cdy = difference(c[1], d[1]);
    const Expansion cdz = difference(c[2], d[2]);

    const Expansion minor_x = add(
        multiply(bdy, cdz), negate(multiply(bdz, cdy)));
    const Expansion minor_y = add(
        multiply(bdx, cdz), negate(multiply(bdz, cdx)));
    const Expansion minor_z = add(
        multiply(bdx, cdy), negate(multiply(bdy, cdx)));
    return sign(add(add(
        multiply(adx, minor_x), negate(multiply(ady, minor_y))),
        multiply(adz, minor_z)));
}

extern "C" const char *scene_v2_exact_predicate_abi() {
    return "scene-v2-expansion-predicates/v1";
}
