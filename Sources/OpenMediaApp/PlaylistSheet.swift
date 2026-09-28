import OpenMediaCore
import SwiftUI

private struct PlaylistRow: Identifiable {
    let id: UUID
    var entry: MediaEntry
    var selected: Bool
    var variant: PlaylistSelection
    init(entry: MediaEntry, variant: PlaylistSelection? = nil) {
        let variant = variant ?? PlaylistSelection(entryID: entry.id)
        id = variant.id
        self.entry = entry
        self.variant = variant
        selected = false
    }
    var estimate: SizeEstimate? {
        entry.estimates.first { $0.media == variant.media && $0.quality == variant.quality && $0.mode == variant.mode }
    }
}

struct PlaylistSheet: View {
    let group: PlaylistGroup
    let copy: AppCopy
    let add: ([PlaylistSelection]) -> Void
    let prioritize: (String) -> Void
    let skip: () -> Void
    @State private var rows: [PlaylistRow]
    @State private var globalMedia = MediaKind.video
    @State private var globalQuality = "best"

    private var boundedWidth: CGFloat {
        min(1030, NSScreen.main?.visibleFrame.width ?? 1030)
    }
    private var boundedHeight: CGFloat {
        min(740, NSScreen.main?.visibleFrame.height ?? 740)
    }

    init(group: PlaylistGroup, copy: AppCopy, add: @escaping ([PlaylistSelection]) -> Void, prioritize: @escaping (String) -> Void, skip: @escaping () -> Void) {
        self.group = group; self.copy = copy; self.add = add; self.prioritize = prioritize; self.skip = skip
        _rows = State(initialValue: group.entries.map { PlaylistRow(entry: $0) })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: "list.bullet.rectangle").font(.system(size: 30)).foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 3) {
                    Text(copy[.playlist]).font(.title2.bold())
                    Text(group.title).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            Text(copy[.playlistHint]).font(.callout).foregroundStyle(.secondary)
            HStack {
                Button(copy[.selectAll]) { for index in rows.indices { rows[index].selected = rows[index].entry.availability != .unavailable } }
                Button(copy[.selectNone]) { for index in rows.indices { rows[index].selected = false } }
                Spacer()
                Text(copy[.allFormats]).foregroundStyle(.secondary)
                MediaPicker(value: $globalMedia, copy: copy).frame(width: 115)
                QualityPicker(value: $globalQuality, media: globalMedia, copy: copy).frame(width: 117)
                Button(copy[.applyAll]) {
                    for index in rows.indices {
                        rows[index].variant.media = globalMedia
                        rows[index].variant.quality = globalQuality
                    }
                }
            }
            .controlSize(.small)
            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    Color.clear.frame(width: 20)
                    Text(copy[.file]).frame(maxWidth: .infinity, alignment: .leading)
                    Text(copy[.format]).frame(width: 105)
                    Text(copy[.quality]).frame(width: 110)
                    Text(copy[.mode]).frame(width: 100)
                    Text(copy[.size]).frame(width: 90)
                    Image(systemName: "plus").frame(width: 29, alignment: .center)
                }
                .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                .padding(.horizontal, 12).frame(height: 40)
                Divider()
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(rows.indices, id: \.self) { index in
                            playlistRow(index)
                            Divider()
                        }
                    }
                }
            }
            .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.secondary.opacity(0.18)))
            .frame(minHeight: 220, idealHeight: 365, maxHeight: 450)
            HStack {
                Text("\(copy[.mediaVariants]): \(rows.filter(\.selected).count)")
                    .font(.callout).foregroundStyle(.secondary)
                Spacer()
                Button(copy[.skipPlaylist], action: skip).keyboardShortcut(.cancelAction)
                Button(copy[.addSelected]) { add(rows.filter(\.selected).map(\.variant)) }
                    .buttonStyle(.borderedProminent)
                    .disabled(!rows.contains(where: \.selected) || rows.contains(where: { $0.selected && $0.entry.availability == .unknown }))
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(22)
        .frame(width: boundedWidth)
        .frame(maxHeight: boundedHeight)
        .onChange(of: globalMedia) { _, newValue in globalQuality = QualityOptions.values(for: newValue)[0] }
        .onChange(of: group.entries) { _, entries in
            rows = Self.reconcile(rows: rows, with: entries)
        }
    }

    private static func reconcile(rows: [PlaylistRow], with entries: [MediaEntry]) -> [PlaylistRow] {
        var result = rows
        var indicesByEntryID: [String: [Int]] = [:]
        var urls = Set<String>()
        for index in result.indices {
            indicesByEntryID[result[index].entry.id, default: []].append(index)
            urls.insert(result[index].entry.url)
        }

        for entry in entries {
            if let indices = indicesByEntryID[entry.id] {
                for index in indices { result[index].entry = entry }
                urls.insert(entry.url)
            } else if urls.insert(entry.url).inserted {
                let index = result.count
                result.append(PlaylistRow(entry: entry))
                indicesByEntryID[entry.id] = [index]
            }
        }
        return result
    }

    @ViewBuilder
    private func playlistRow(_ index: Int) -> some View {
        let row = rows[index]
        HStack(spacing: 12) {
            Toggle(copy[.file], isOn: Binding(get: { rows[index].selected }, set: { selected in
                rows[index].selected = selected
                if selected && row.entry.availability == .unknown { prioritize(row.entry.id) }
            })).labelsHidden().toggleStyle(.checkbox).frame(width: 20)
                .disabled(row.entry.availability == .unavailable)
            VStack(alignment: .leading, spacing: 4) {
                Text(row.entry.title).font(.system(size: 12, weight: .medium)).lineLimit(1)
                Text(copy.availability(row.entry.availability)).font(.caption)
                    .foregroundStyle(row.entry.availability == .unavailable ? Color.red : row.entry.availability == .authenticationRequired ? Color.orange : Color.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .help(row.entry.title + (row.entry.error.map { "\n\($0)" } ?? "\n\(row.entry.url)"))
            MediaPicker(value: Binding(get: { rows[index].variant.media }, set: {
                rows[index].variant.media = $0
                rows[index].variant.quality = QualityOptions.values(for: $0)[0]
            }), copy: copy).frame(width: 105)
            QualityPicker(value: $rows[index].variant.quality, media: row.variant.media, copy: copy).frame(width: 110)
            ModePicker(value: $rows[index].variant.mode, copy: copy).frame(width: 100)
            Text(copy.estimate(row.estimate)).font(.caption).monospacedDigit().frame(width: 90)
                .help(copy[.estimatesHint])
            SquareSymbolButton(symbol: "plus", help: copy[.addVariant]) {
                let variant = PlaylistSelection(entryID: row.entry.id, media: row.variant.media, quality: row.variant.quality, mode: row.variant.mode)
                rows.insert(PlaylistRow(entry: row.entry, variant: variant), at: index + 1)
            }.disabled(row.entry.availability == .unavailable)
        }
        .controlSize(.small)
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(index.isMultiple(of: 2) ? Color.clear : Color.primary.opacity(0.025))
    }
}
