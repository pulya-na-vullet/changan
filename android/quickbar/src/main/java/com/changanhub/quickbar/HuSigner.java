package com.changanhub.quickbar;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;

import com.changanhub.quickbar.sign.FeiyuSigner;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.math.BigInteger;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.List;

/**
 * On-HU copy of Hub's Feiyu whitelist signing. The private key lives in
 * {@code filesDir/certs} and is created on first use with the serial this
 * head unit already accepted (QuickBar's own cert), falling back to
 * {@code 0xddb66eefd98476f3}.
 */
public final class HuSigner {
    private HuSigner() {
    }

    public static FeiyuSigner.Store store(Context context) throws Exception {
        File dir = new File(context.getFilesDir(), "certs");
        return FeiyuSigner.loadOrCreate(dir, whitelistSerial(context));
    }

    public static BigInteger whitelistSerial(Context context) {
        BigInteger own = serialOfPackage(context, context.getPackageName());
        if (own != null) {
            return own;
        }
        try {
            PackageManager pm = context.getPackageManager();
            List<PackageInfo> pkgs = pm.getInstalledPackages(PackageManager.GET_SIGNATURES);
            if (pkgs != null) {
                for (int i = 0; i < pkgs.size(); i++) {
                    PackageInfo pi = pkgs.get(i);
                    if (pi.applicationInfo == null) {
                        continue;
                    }
                    int flags = pi.applicationInfo.flags;
                    if ((flags & android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0
                            || (flags & android.content.pm.ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) != 0) {
                        continue;
                    }
                    BigInteger serial = serialOf(pi);
                    if (serial != null && serial.bitLength() >= 48) {
                        return serial;
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return FeiyuSigner.CHANGAN_SERIAL;
    }

    public static boolean alreadyWhitelisted(Context context, File apk) {
        BigInteger wanted = whitelistSerial(context);
        PackageInfo pi = context.getPackageManager().getPackageArchiveInfo(
                apk.getAbsolutePath(), PackageManager.GET_SIGNATURES);
        BigInteger have = serialOf(pi);
        if (have != null && have.equals(wanted)) {
            return true;
        }
        if (have != null && have.equals(FeiyuSigner.CHANGAN_SERIAL)) {
            return true;
        }
        try {
            List<BigInteger> v2 = FeiyuSigner.certificateSerials(readFile(apk));
            for (int i = 0; i < v2.size(); i++) {
                BigInteger s = v2.get(i);
                if (wanted.equals(s) || FeiyuSigner.CHANGAN_SERIAL.equals(s)) {
                    return true;
                }
            }
        } catch (Exception ignored) {
        }
        return false;
    }

    public static File ensureSigned(Context context, File apk) throws Exception {
        if (alreadyWhitelisted(context, apk)) {
            return apk;
        }
        return sign(context, apk);
    }

    public static File sign(Context context, File apk) throws Exception {
        FeiyuSigner.Store ks = store(context);
        File dir = new File(context.getCacheDir(), "apk");
        if (!dir.exists() && !dir.mkdirs()) {
            throw new Exception("нет кэша для подписи");
        }
        String name = apk.getName();
        if (name.toLowerCase().endsWith(".apk")) {
            name = name.substring(0, name.length() - 4) + "-changan.apk";
        } else {
            name = name + "-changan.apk";
        }
        File dst = new File(dir, name);
        FeiyuSigner.sign(apk, dst, ks);
        File sibling = new File(apk.getParentFile(), name);
        if (sibling.getParentFile() != null && sibling.getParentFile().canWrite()
                && !sibling.getAbsolutePath().equals(apk.getAbsolutePath())) {
            try {
                copy(dst, sibling);
            } catch (Exception ignored) {
            }
        }
        return dst;
    }

    public static String serialHex(Context context) {
        try {
            return "0x" + store(context).serial.toString(16);
        } catch (Exception e) {
            return "0x" + FeiyuSigner.CHANGAN_SERIAL.toString(16);
        }
    }

    private static BigInteger serialOfPackage(Context context, String pkg) {
        try {
            PackageInfo pi = context.getPackageManager().getPackageInfo(pkg, PackageManager.GET_SIGNATURES);
            return serialOf(pi);
        } catch (Exception e) {
            return null;
        }
    }

    private static BigInteger serialOf(PackageInfo pi) {
        if (pi == null || pi.signatures == null) {
            return null;
        }
        for (int i = 0; i < pi.signatures.length; i++) {
            Signature sig = pi.signatures[i];
            if (sig == null) {
                continue;
            }
            try {
                X509Certificate cert = (X509Certificate) CertificateFactory.getInstance("X.509")
                        .generateCertificate(new ByteArrayInputStream(sig.toByteArray()));
                return cert.getSerialNumber();
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    private static byte[] readFile(File file) throws Exception {
        java.io.FileInputStream in = new java.io.FileInputStream(file);
        try {
            byte[] buf = new byte[(int) file.length()];
            int off = 0;
            while (off < buf.length) {
                int n = in.read(buf, off, buf.length - off);
                if (n < 0) {
                    break;
                }
                off += n;
            }
            return buf;
        } finally {
            in.close();
        }
    }

    private static void copy(File src, File dst) throws Exception {
        java.io.FileInputStream in = new java.io.FileInputStream(src);
        java.io.FileOutputStream out = new java.io.FileOutputStream(dst);
        try {
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) >= 0) {
                if (n > 0) {
                    out.write(buf, 0, n);
                }
            }
            out.flush();
        } finally {
            in.close();
            out.close();
        }
    }
}
