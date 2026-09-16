package com.changanhub.player;

import android.app.Activity;
import android.content.ContentUris;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.database.Cursor;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;
import android.provider.DocumentsContract;
import android.provider.MediaStore;

import java.io.File;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Feiyu FUSE {@code /storage/UUID} lists names and yields zeros. Kernel
 * {@code /mnt/media_rw} is EACCES for a normal APK. The OEM music app is a
 * system process and still often fails the same way if it opens FUSE.
 * Bytes come from MediaProvider ({@code content://media/…}) or from a
 * granted Documents tree ({@code StorageVolume.createAccessIntent}).
 */
public final class UsbBridge {
    public static final int REQUEST = 71;
    public static final String ACTION_NEED_ACCESS = "com.changanhub.player.NEED_USB_ACCESS";
    private static final String PREFS = "usb_bridge";

    private UsbBridge() {
    }

    public static InputStream open(Context context, File file) {
        if (context == null || file == null) {
            return null;
        }
        InputStream fromStore = openStore(context, file);
        if (fromStore != null) {
            return fromStore;
        }
        return openTree(context, file);
    }

    public static InputStream scanAndOpen(Context context, File file) {
        if (context == null || file == null) {
            return null;
        }
        File[] cands = UsbMedia.expandKernelCandidates(file);
        ArrayList<String> paths = new ArrayList<>();
        addScanPath(paths, file);
        for (int i = 0; i < cands.length && paths.size() < 8; i++) {
            addScanPath(paths, cands[i]);
        }
        if (!paths.isEmpty()) {
            final CountDownLatch latch = new CountDownLatch(1);
            try {
                String[] arr = paths.toArray(new String[0]);
                MediaScannerConnection.scanFile(context, arr, null,
                        new MediaScannerConnection.OnScanCompletedListener() {
                            @Override
                            public void onScanCompleted(String path, Uri uri) {
                                latch.countDown();
                            }
                        });
                latch.await(8, TimeUnit.SECONDS);
            } catch (Exception ignored) {
            }
        }
        return open(context, file);
    }

    public static boolean hasTree(Context context, File file) {
        return treeUri(context, file) != null;
    }

    public static boolean requestAccess(Activity activity, File file) {
        if (activity == null) {
            return false;
        }
        Intent intent = accessIntent(activity, file);
        if (intent == null) {
            intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        }
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        try {
            activity.startActivityForResult(intent, REQUEST);
            return true;
        } catch (Exception e) {
            try {
                Intent tree = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
                tree.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                        | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
                activity.startActivityForResult(tree, REQUEST);
                return true;
            } catch (Exception ignored) {
                return false;
            }
        }
    }

    public static void saveResult(Activity activity, int requestCode, int resultCode, Intent data) {
        if (requestCode != REQUEST || resultCode != Activity.RESULT_OK || data == null) {
            return;
        }
        Uri uri = data.getData();
        if (uri == null || activity == null) {
            return;
        }
        int flags = data.getFlags()
                & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        if (flags == 0) {
            flags = Intent.FLAG_GRANT_READ_URI_PERMISSION;
        }
        try {
            activity.getContentResolver().takePersistableUriPermission(uri, flags);
        } catch (Exception ignored) {
        }
        SharedPreferences p = activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        p.edit().putString("tree_last", uri.toString()).apply();
        String uuid = uuidFromTree(uri);
        if (uuid != null) {
            p.edit().putString("tree_" + uuid.toLowerCase(Locale.US), uri.toString()).apply();
        }
    }

    static Intent accessIntent(Context context, File file) {
        StorageVolume volume = matchingVolume(context, file);
        if (volume == null) {
            return null;
        }
        try {
            Method m = StorageVolume.class.getMethod("createAccessIntent", String.class);
            Intent intent = (Intent) m.invoke(volume, (String) null);
            if (intent != null) {
                return intent;
            }
            intent = (Intent) m.invoke(volume, Environment.DIRECTORY_MUSIC);
            if (intent != null) {
                return intent;
            }
        } catch (Exception ignored) {
        }
        try {
            Method m = StorageVolume.class.getMethod("createOpenDocumentTreeIntent");
            Object intent = m.invoke(volume);
            if (intent instanceof Intent) {
                return (Intent) intent;
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private static InputStream openStore(Context context, File file) {
        Uri[] tables = storeTables(file);
        String name = file.getName();
        String[] likes = new String[] {
                name,
                "%/" + name,
                "%" + name
        };
        String[] columns = new String[] {
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.DATA,
                MediaStore.MediaColumns.DATA
        };
        for (int t = 0; t < tables.length; t++) {
            for (int c = 0; c < columns.length; c++) {
                Uri found = queryStore(context, tables[t], columns[c], likes[c], name);
                if (found == null) {
                    continue;
                }
                InputStream in = openChecked(context, found);
                if (in != null) {
                    return in;
                }
            }
        }
        return null;
    }

    private static Uri[] storeTables(File file) {
        ArrayList<Uri> out = new ArrayList<>();
        String uuid = UsbMedia.volumeName(file.getAbsolutePath());
        if (uuid != null) {
            String lower = uuid.toLowerCase(Locale.US);
            String[] vols = { lower, uuid };
            String[] kinds = { "file", "audio/media", "video/media" };
            for (int v = 0; v < vols.length; v++) {
                for (int k = 0; k < kinds.length; k++) {
                    out.add(Uri.parse("content://media/" + vols[v] + "/" + kinds[k]));
                }
            }
        }
        out.add(MediaStore.Files.getContentUri("external"));
        out.add(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI);
        out.add(MediaStore.Video.Media.EXTERNAL_CONTENT_URI);
        out.add(Uri.parse("content://media/external/file"));
        out.add(Uri.parse("content://media/external_primary/file"));
        return out.toArray(new Uri[0]);
    }

    private static Uri queryStore(Context context, Uri table, String column, String value, String name) {
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    table,
                    new String[] { MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DATA },
                    column + " LIKE ?",
                    new String[] { value },
                    null);
            if (cursor != null) {
                while (cursor.moveToNext()) {
                    long id = cursor.getLong(0);
                    String data = cursor.getColumnCount() > 1 ? cursor.getString(1) : null;
                    if (data != null && name != null && !data.endsWith(name) && !data.contains("/" + name)) {
                        continue;
                    }
                    return ContentUris.withAppendedId(table, id);
                }
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                try {
                    cursor.close();
                } catch (Exception ignored) {
                }
            }
        }
        return null;
    }

    private static InputStream openTree(Context context, File file) {
        Uri tree = treeUri(context, file);
        if (tree == null) {
            return null;
        }
        String rel = UsbMedia.volumeRelative(file);
        String uuid = UsbMedia.volumeName(file.getAbsolutePath());
        if (uuid == null) {
            uuid = uuidFromTree(tree);
        }
        if (uuid != null && rel.length() > 0) {
            try {
                String docId = uuid + ":" + rel;
                Uri doc = DocumentsContract.buildDocumentUriUsingTree(tree, docId);
                InputStream in = openChecked(context, doc);
                if (in != null) {
                    return in;
                }
            } catch (Exception ignored) {
            }
        }
        try {
            String rootId = DocumentsContract.getTreeDocumentId(tree);
            Uri found = findDoc(context, tree, rootId, file.getName(), 0);
            if (found != null) {
                return openChecked(context, found);
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private static Uri findDoc(Context context, Uri tree, String parentId, String name, int depth) {
        if (depth > 4 || name == null) {
            return null;
        }
        Uri children;
        try {
            children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId);
        } catch (Exception e) {
            return null;
        }
        Cursor cursor = null;
        ArrayList<String> dirs = new ArrayList<>();
        try {
            cursor = context.getContentResolver().query(
                    children,
                    new String[] {
                            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                            DocumentsContract.Document.COLUMN_MIME_TYPE
                    },
                    null,
                    null,
                    null);
            if (cursor == null) {
                return null;
            }
            while (cursor.moveToNext()) {
                String id = cursor.getString(0);
                String display = cursor.getString(1);
                String mime = cursor.getString(2);
                if (name.equals(display)) {
                    return DocumentsContract.buildDocumentUriUsingTree(tree, id);
                }
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    dirs.add(id);
                }
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                try {
                    cursor.close();
                } catch (Exception ignored) {
                }
            }
        }
        for (int i = 0; i < dirs.size(); i++) {
            Uri found = findDoc(context, tree, dirs.get(i), name, depth + 1);
            if (found != null) {
                return found;
            }
        }
        return null;
    }

    private static Uri treeUri(Context context, File file) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String uuid = file == null ? null : UsbMedia.volumeName(file.getAbsolutePath());
        String stored = null;
        if (uuid != null) {
            stored = p.getString("tree_" + uuid.toLowerCase(Locale.US), null);
        }
        if (stored == null || stored.length() == 0) {
            stored = p.getString("tree_last", null);
        }
        if (stored != null && stored.length() > 0) {
            try {
                return Uri.parse(stored);
            } catch (Exception ignored) {
            }
        }
        try {
            List<UriPermission> granted = context.getContentResolver().getPersistedUriPermissions();
            for (int i = 0; i < granted.size(); i++) {
                Uri uri = granted.get(i).getUri();
                if (uri != null && granted.get(i).isReadPermission()) {
                    return uri;
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    static InputStream openChecked(Context context, Uri uri) {
        if (uri == null) {
            return null;
        }
        byte[] head = new byte[64];
        int n = -1;
        InputStream peek = null;
        try {
            peek = context.getContentResolver().openInputStream(uri);
            if (peek == null) {
                ParcelFileDescriptor pfd = context.getContentResolver().openFileDescriptor(uri, "r");
                if (pfd == null) {
                    return null;
                }
                peek = new ParcelFileDescriptor.AutoCloseInputStream(pfd);
            }
            n = peek.read(head);
        } catch (Exception e) {
            return null;
        } finally {
            if (peek != null) {
                try {
                    peek.close();
                } catch (Exception ignored) {
                }
            }
        }
        if (n < 1) {
            return null;
        }
        int nz = 0;
        for (int i = 0; i < n; i++) {
            if (head[i] != 0) {
                nz++;
            }
        }
        if (nz == 0) {
            return null;
        }
        if (!MediaSource.looksLikeMedia(head, n) && nz < 4) {
            return null;
        }
        try {
            InputStream in = context.getContentResolver().openInputStream(uri);
            if (in != null) {
                return in;
            }
        } catch (Exception ignored) {
        }
        try {
            ParcelFileDescriptor pfd = context.getContentResolver().openFileDescriptor(uri, "r");
            if (pfd != null) {
                return new ParcelFileDescriptor.AutoCloseInputStream(pfd);
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private static StorageVolume matchingVolume(Context context, File file) {
        try {
            StorageManager sm = (StorageManager) context.getSystemService(Context.STORAGE_SERVICE);
            if (sm == null) {
                return null;
            }
            String uuid = file == null ? null : UsbMedia.volumeName(file.getAbsolutePath());
            List<StorageVolume> vols = sm.getStorageVolumes();
            StorageVolume removable = null;
            Method getUuid = StorageVolume.class.getMethod("getUuid");
            for (int i = 0; i < vols.size(); i++) {
                StorageVolume v = vols.get(i);
                if (v.isPrimary()) {
                    continue;
                }
                removable = v;
                Object vu = getUuid.invoke(v);
                if (uuid != null && vu instanceof String && uuid.equalsIgnoreCase((String) vu)) {
                    return v;
                }
            }
            return removable;
        } catch (Exception e) {
            return null;
        }
    }

    private static String uuidFromTree(Uri uri) {
        if (uri == null) {
            return null;
        }
        try {
            String doc = DocumentsContract.getTreeDocumentId(uri);
            if (doc == null) {
                return UsbMedia.volumeName(uri.toString());
            }
            int colon = doc.indexOf(':');
            String vol = colon >= 0 ? doc.substring(0, colon) : doc;
            return UsbMedia.volumeName("/storage/" + vol) != null ? vol : UsbMedia.volumeName(vol);
        } catch (Exception e) {
            return UsbMedia.volumeName(uri.toString());
        }
    }

    private static void addScanPath(List<String> paths, File file) {
        if (file == null || UsbMedia.looksLikeDirectory(file)) {
            return;
        }
        String path = file.getAbsolutePath();
        if (path.length() == 0 || paths.contains(path)) {
            return;
        }
        paths.add(path);
    }
}
