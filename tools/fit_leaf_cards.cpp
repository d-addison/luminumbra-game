// Offline derivative of Tree Small 02's disconnected leaf surfaces.
// Fit each source leaf in its own UV coordinates; retain every leaf, its UV
// rectangle, placement and facing. No spatial decimation or random thinning.
// Input/output: Luminumbra LMESH v1, little endian, position/normal/UV vertices.
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <stdexcept>
#include <unordered_map>
#include <vector>

struct Vertex {
    float p[3], n[3], uv[2];
};
struct Header {
    uint32_t magic, vertices, indices;
    float sphere[4];
};
static_assert(sizeof(Vertex) == 32 && sizeof(Header) == 28);
using Key = std::array<uint32_t, 3>;
struct KeyHash {
    size_t operator()(const Key& k) const {
        size_t h = 2166136261u;
        for (auto x : k)
            h = (h ^ x) * 16777619u;
        return h;
    }
};

int main(int argc, char** argv) try {
    if (argc != 3 || std::endian::native != std::endian::little)
        throw std::runtime_error("Usage: fit_leaf_cards source.lmesh output.lmesh (little endian)");
    std::ifstream input(argv[1], std::ios::binary | std::ios::ate);
    const auto bytes = input.tellg();
    input.seekg(0);
    Header h{};
    input.read(reinterpret_cast<char*>(&h), sizeof h);
    if (!input || h.magic != 0x48534d4c || !h.vertices || !h.indices || h.indices % 3 ||
        h.vertices > 4'000'000 || h.indices > 12'000'000 || bytes < 0 ||
        static_cast<uint64_t>(bytes) != 28ull + h.vertices * 32ull + h.indices * 4ull)
        throw std::runtime_error("Invalid source LMESH header or byte count");
    std::vector<Vertex> vertices(h.vertices);
    std::vector<uint32_t> indices(h.indices), parent(h.vertices);
    input.read(reinterpret_cast<char*>(vertices.data()), vertices.size() * sizeof(Vertex));
    input.read(reinterpret_cast<char*>(indices.data()), indices.size() * sizeof(uint32_t));
    if (!input)
        throw std::runtime_error("Truncated source LMESH");
    std::iota(parent.begin(), parent.end(), 0u);
    auto root = [&](uint32_t i) {
        while (parent[i] != i) {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    };
    auto join = [&](uint32_t a, uint32_t b) {
        a = root(a);
        b = root(b);
        parent[std::max(a, b)] = std::min(a, b);
    };
    std::unordered_map<Key, uint32_t, KeyHash> positions;
    positions.reserve(vertices.size());
    for (uint32_t i = 0; i < vertices.size(); ++i) {
        const auto& v = vertices[i];
        for (float x : v.p)
            if (!std::isfinite(x))
                throw std::runtime_error("Nonfinite position");
        for (float x : v.n)
            if (!std::isfinite(x))
                throw std::runtime_error("Nonfinite normal");
        for (float x : v.uv)
            if (!std::isfinite(x))
                throw std::runtime_error("Nonfinite UV");
        Key key{};
        for (int k = 0; k < 3; ++k)
            key[k] = std::bit_cast<uint32_t>(v.p[k] == 0 ? 0.f : v.p[k]);
        auto [it, inserted] = positions.emplace(key, i);
        if (!inserted)
            join(i, it->second);
    }
    for (size_t t = 0; t < indices.size(); t += 3) {
        for (int j = 0; j < 3; ++j)
            if (indices[t + j] >= vertices.size())
                throw std::runtime_error("Out-of-range index");
        join(indices[t], indices[t + 1]);
        join(indices[t], indices[t + 2]);
    }
    std::map<uint32_t, std::vector<uint32_t>> groups;
    for (uint32_t i = 0; i < vertices.size(); ++i)
        groups[root(i)].push_back(i);
    if (groups.size() > 100'000)
        throw std::runtime_error("Too many leaf surfaces");
    std::vector<Vertex> cards;
    std::vector<uint32_t> triangles;
    double maximum_error = 0;
    for (const auto& [id, group] : groups) {
        (void)id;
        std::array<double, 2> lo{1e30, 1e30}, hi{-1e30, -1e30}, mid{}, span{};
        std::array<double, 3> pmin{1e30, 1e30, 1e30}, pmax{-1e30, -1e30, -1e30}, avg{};
        for (auto i : group) {
            for (int k = 0; k < 2; ++k) {
                lo[k] = std::min(lo[k], double(vertices[i].uv[k]));
                hi[k] = std::max(hi[k], double(vertices[i].uv[k]));
            }
            for (int k = 0; k < 3; ++k) {
                pmin[k] = std::min(pmin[k], double(vertices[i].p[k]));
                pmax[k] = std::max(pmax[k], double(vertices[i].p[k]));
                avg[k] += vertices[i].n[k];
            }
        }
        for (int k = 0; k < 2; ++k) {
            mid[k] = (hi[k] + lo[k]) * .5;
            span[k] = (hi[k] - lo[k]) * .5;
            if (span[k] < 1e-8)
                throw std::runtime_error("Degenerate leaf UVs");
        }
        double a[3][6]{};
        for (auto i : group) {
            const auto& v = vertices[i];
            const double x[3] = {(v.uv[0] - mid[0]) / span[0], (v.uv[1] - mid[1]) / span[1], 1};
            for (int r = 0; r < 3; ++r) {
                for (int c = 0; c < 3; ++c)
                    a[r][c] += x[r] * x[c];
                for (int c = 0; c < 3; ++c)
                    a[r][3 + c] += x[r] * v.p[c];
            }
        }
        // Pivoted least-squares normal equations, normalized to the leaf's UV box.
        for (int k = 0; k < 3; ++k) {
            int pivot = k;
            for (int r = k + 1; r < 3; ++r)
                if (std::abs(a[r][k]) > std::abs(a[pivot][k]))
                    pivot = r;
            if (std::abs(a[pivot][k]) < 1e-10)
                throw std::runtime_error("Singular leaf fit");
            for (int c = 0; c < 6; ++c)
                std::swap(a[k][c], a[pivot][c]);
            const double scale = a[k][k];
            for (int c = k; c < 6; ++c)
                a[k][c] /= scale;
            for (int r = 0; r < 3; ++r)
                if (r != k) {
                    const double factor = a[r][k];
                    for (int c = k; c < 6; ++c)
                        a[r][c] -= factor * a[k][c];
                }
        }
        double diagonal = 0, residual = 0;
        for (int k = 0; k < 3; ++k)
            diagonal += (pmax[k] - pmin[k]) * (pmax[k] - pmin[k]);
        for (auto i : group) {
            double squared = 0;
            for (int k = 0; k < 3; ++k) {
                const double predicted = a[0][3 + k] * (vertices[i].uv[0] - mid[0]) / span[0] +
                                         a[1][3 + k] * (vertices[i].uv[1] - mid[1]) / span[1] +
                                         a[2][3 + k];
                squared += (predicted - vertices[i].p[k]) * (predicted - vertices[i].p[k]);
            }
            residual = std::max(residual, squared);
        }
        const double relative_error = std::sqrt(residual / diagonal);
        if (!std::isfinite(relative_error) || relative_error > .2)
            throw std::runtime_error("Source leaf exceeds the reviewed planar approximation bound");
        maximum_error = std::max(maximum_error, relative_error);
        double n[3]{}, length = 0, facing = 0;
        for (int k = 0; k < 3; ++k) {
            const int b = (k + 1) % 3, c = (k + 2) % 3;
            n[k] = a[0][3 + b] * a[1][3 + c] - a[0][3 + c] * a[1][3 + b];
            length += n[k] * n[k];
            facing += n[k] * avg[k];
        }
        if (length < 1e-20)
            throw std::runtime_error("Degenerate fitted card");
        const bool flip = facing < 0;
        const double normal_scale = (flip ? -1 : 1) / std::sqrt(length);
        const uint32_t base = static_cast<uint32_t>(cards.size());
        for (const auto& xy :
             {std::array{-1., -1.}, std::array{1., -1.}, std::array{1., 1.}, std::array{-1., 1.}}) {
            Vertex v{};
            for (int k = 0; k < 3; ++k) {
                v.p[k] = float(a[0][3 + k] * xy[0] + a[1][3 + k] * xy[1] + a[2][3 + k]);
                v.n[k] = float(n[k] * normal_scale);
            }
            for (int k = 0; k < 2; ++k)
                v.uv[k] = float(xy[k] * span[k] + mid[k]);
            cards.push_back(v);
        }
        for (uint32_t i :
             (flip ? std::array{0u, 2u, 1u, 0u, 3u, 2u} : std::array{0u, 1u, 2u, 0u, 2u, 3u}))
            triangles.push_back(base + i);
    }
    // Keep the source centre and expand conservatively for fitted corners.
    for (const auto& v : cards) {
        double r2 = 0;
        for (int k = 0; k < 3; ++k)
            r2 += double(v.p[k] - h.sphere[k]) * (v.p[k] - h.sphere[k]);
        h.sphere[3] =
            std::max(h.sphere[3],
                     std::nextafter(float(std::sqrt(r2)), std::numeric_limits<float>::infinity()));
    }
    h.vertices = static_cast<uint32_t>(cards.size());
    h.indices = static_cast<uint32_t>(triangles.size());
    std::ofstream output(argv[2], std::ios::binary);
    output.write(reinterpret_cast<const char*>(&h), sizeof h);
    output.write(reinterpret_cast<const char*>(cards.data()), cards.size() * sizeof(Vertex));
    output.write(reinterpret_cast<const char*>(triangles.data()),
                 triangles.size() * sizeof(uint32_t));
    output.flush();
    if (!output)
        throw std::runtime_error("Could not write leaf cards");
    std::cout << "{\"leaf_surfaces\":" << groups.size() << ",\"triangles\":" << triangles.size() / 3
              << ",\"maximum_relative_fit_error\":" << maximum_error << "}\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
}
