package com.changanhub.quickbar.sign;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.math.BigInteger;
import java.nio.charset.Charset;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.TimeZone;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

/**
 * Feiyu whitelist APK signing (v1 JAR + v2), same rules as Changan Hub:
 * X.509 serial {@code 0xddb66eefd98476f3} (or the HU's own serial), no extra
 * extensions, PKCS7 CERT.RSA without SMIME capabilities.
 */
public final class FeiyuSigner {
    public static final BigInteger CHANGAN_SERIAL = new BigInteger("ddb66eefd98476f3", 16);
    public static final String CREATED = "Changan Hub";

    private static final Charset US = Charset.forName("US-ASCII");
    private static final Charset UTF8 = Charset.forName("UTF-8");
    private static final byte[] V2_MAGIC = "APK Sig Block 42".getBytes(US);
    private static final int V2_ID = 0x7109871A;
    private static final int RSA_PKCS1_SHA256 = 0x0103;
    private static final int CHUNK = 1024 * 1024;

    private FeiyuSigner() {
    }

    public static final class Store {
        public final File directory;
        public final PrivateKey key;
        public final byte[] certDer;
        public final BigInteger serial;

        Store(File directory, PrivateKey key, byte[] certDer, BigInteger serial) {
            this.directory = directory;
            this.key = key;
            this.certDer = certDer;
            this.serial = serial;
        }
    }

    public static Store loadOrCreate(File directory, BigInteger serial) throws Exception {
        if (!directory.exists() && !directory.mkdirs()) {
            throw new IOException("certs: " + directory);
        }
        File keyFile = new File(directory, "changan.pk8");
        File certFile = new File(directory, "changan.der");
        if (keyFile.isFile() && certFile.isFile()) {
            try {
                PrivateKey key = KeyFactory.getInstance("RSA").generatePrivate(
                        new PKCS8EncodedKeySpec(readAll(keyFile)));
                byte[] der = readAll(certFile);
                X509Certificate cert = loadCert(der);
                if (cert.getSerialNumber().equals(serial) && !hasExtensions(cert)) {
                    return new Store(directory, key, der, serial);
                }
            } catch (Exception ignored) {
            }
        }
        return generate(directory, serial);
    }

    static boolean hasExtensions(X509Certificate cert) {
        return (cert.getCriticalExtensionOIDs() != null && !cert.getCriticalExtensionOIDs().isEmpty())
                || (cert.getNonCriticalExtensionOIDs() != null && !cert.getNonCriticalExtensionOIDs().isEmpty());
    }

    public static Store generate(File directory, BigInteger serial) throws Exception {
        if (!directory.exists() && !directory.mkdirs()) {
            throw new IOException("certs: " + directory);
        }
        KeyPairGenerator gen = KeyPairGenerator.getInstance("RSA");
        gen.initialize(2048);
        KeyPair pair = gen.generateKeyPair();
        Calendar now = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        now.add(Calendar.DAY_OF_MONTH, -1);
        Calendar until = (Calendar) now.clone();
        until.add(Calendar.DAY_OF_MONTH, 18250);
        byte[] tbs = tbsCertificate(pair, serial, now, until);
        Signature sig = Signature.getInstance("SHA256withRSA");
        sig.initSign(pair.getPrivate());
        sig.update(tbs);
        byte[] signature = sig.sign();
        byte[] cert = seq(tbs, algId(OID_SHA256_RSA), bitString(signature));
        writeAll(new File(directory, "changan.pk8"), pair.getPrivate().getEncoded());
        writeAll(new File(directory, "changan.der"), cert);
        writeAll(new File(directory, "serial.txt"), serial.toString(16).getBytes(US));
        return new Store(directory, pair.getPrivate(), cert, serial);
    }

    public static void sign(File src, File dst, Store store) throws Exception {
        List<ZipItem> items = new ArrayList<ZipItem>();
        ZipFile zin = new ZipFile(src);
        try {
            java.util.Enumeration<? extends ZipEntry> en = zin.entries();
            while (en.hasMoreElements()) {
                ZipEntry e = en.nextElement();
                String name = e.getName();
                String upper = name.toUpperCase();
                if (upper.startsWith("META-INF/") && (upper.endsWith(".SF") || upper.endsWith(".RSA")
                        || upper.endsWith(".DSA") || upper.endsWith(".EC") || upper.endsWith(".MF"))) {
                    continue;
                }
                if (e.isDirectory()) {
                    continue;
                }
                items.add(new ZipItem(name, readStream(zin.getInputStream(e)), e.getMethod()));
            }
        } finally {
            zin.close();
        }

        StringBuilder mf = new StringBuilder();
        mf.append("Manifest-Version: 1.0\nCreated-By: ").append(CREATED).append("\n\n");
        for (int i = 0; i < items.size(); i++) {
            ZipItem it = items.get(i);
            mf.append("Name: ").append(it.name).append("\nSHA-256-Digest: ")
                    .append(b64(sha256(it.data))).append("\n\n");
        }
        byte[] manifest = wrap72(mf.toString()).getBytes(US);

        StringBuilder sf = new StringBuilder();
        sf.append("Signature-Version: 1.0\nCreated-By: ").append(CREATED).append("\n");
        sf.append("SHA-256-Digest-Manifest: ").append(b64(sha256(manifest))).append("\n\n");
        String[] blocks = new String(manifest, US).split("\n\n");
        for (int i = 0; i < blocks.length; i++) {
            String block = blocks[i];
            if (!block.startsWith("Name: ")) {
                continue;
            }
            String name = block.substring(6).split("\n", 2)[0];
            byte[] section = wrap72(block + "\n").getBytes(US);
            sf.append("Name: ").append(name).append("\nSHA-256-Digest: ")
                    .append(b64(sha256(section))).append("\n\n");
        }
        byte[] sfBytes = wrap72(sf.toString()).getBytes(US);
        byte[] rsa = pkcs7(store, sfBytes);

        List<ZipItem> ordered = new ArrayList<ZipItem>();
        ordered.add(new ZipItem("META-INF/MANIFEST.MF", manifest, ZipEntry.DEFLATED));
        ordered.add(new ZipItem("META-INF/CERT.SF", sfBytes, ZipEntry.DEFLATED));
        ordered.add(new ZipItem("META-INF/CERT.RSA", rsa, ZipEntry.DEFLATED));
        ordered.addAll(items);

        File tmp = File.createTempFile("qb-sign", ".apk", dst.getParentFile());
        writeZip(tmp, ordered);
        byte[] signed = attachV2(readAll(tmp), store);
        tmp.delete();
        writeAll(dst, signed);
    }

    public static boolean hasV2(byte[] apk) {
        try {
            int eocd = findEocd(apk);
            return signingBlockStart(apk, cdOffset(apk, eocd)) >= 0;
        } catch (Exception e) {
            return false;
        }
    }

    public static List<BigInteger> certificateSerials(byte[] apk) {
        List<BigInteger> out = new ArrayList<BigInteger>();
        try {
            for (byte[] der : v2Certs(apk)) {
                out.add(loadCert(der).getSerialNumber());
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("gen <dir> [serialHex] | sign <dir> <src> <dst>");
            System.exit(2);
        }
        if ("gen".equals(args[0])) {
            BigInteger serial = args.length > 2 ? new BigInteger(args[2], 16) : CHANGAN_SERIAL;
            Store store = generate(new File(args[1]), serial);
            System.out.println(store.serial.toString(16));
            return;
        }
        if ("sign".equals(args[0]) && args.length >= 4) {
            Store store = loadOrCreate(new File(args[1]), CHANGAN_SERIAL);
            sign(new File(args[2]), new File(args[3]), store);
            System.out.println("ok");
            return;
        }
        System.exit(2);
    }

    private static final class ZipItem {
        final String name;
        final byte[] data;
        final int method;

        ZipItem(String name, byte[] data, int method) {
            this.name = name;
            this.data = data;
            this.method = method;
        }
    }

    private static void writeZip(File dst, List<ZipItem> items) throws IOException {
        FileOutputStream raw = new FileOutputStream(dst);
        CountOut count = new CountOut(raw);
        ZipOutputStream zout = new ZipOutputStream(count);
        try {
            for (int i = 0; i < items.size(); i++) {
                ZipItem it = items.get(i);
                ZipEntry e = new ZipEntry(it.name);
                boolean stored = it.name.replace('\\', '/').startsWith("lib/") && it.name.endsWith(".so");
                int align = stored ? 4096 : 4;
                if (stored) {
                    CRC32 crc = new CRC32();
                    crc.update(it.data);
                    e.setMethod(ZipEntry.STORED);
                    e.setSize(it.data.length);
                    e.setCompressedSize(it.data.length);
                    e.setCrc(crc.getValue());
                } else {
                    e.setMethod(ZipEntry.DEFLATED);
                }
                int nameLen = it.name.getBytes(UTF8).length;
                int extra = 0;
                long header = 30L + nameLen + extra;
                int pad = (int) ((align - (count.n + header) % align) % align);
                if (pad > 0) {
                    e.setExtra(new byte[pad]);
                }
                zout.putNextEntry(e);
                zout.write(it.data);
                zout.closeEntry();
            }
        } finally {
            zout.close();
        }
    }

    private static final class CountOut extends FilterOutputStream {
        long n;

        CountOut(OutputStream out) {
            super(out);
        }

        public void write(int b) throws IOException {
            out.write(b);
            n++;
        }

        public void write(byte[] b, int off, int len) throws IOException {
            out.write(b, off, len);
            n += len;
        }
    }

    private static byte[] tbsCertificate(KeyPair pair, BigInteger serial, Calendar from, Calendar until)
            throws Exception {
        byte[] version = derCtxExplicit(0, integer(BigInteger.valueOf(2)));
        byte[] serialDer = integer(serial);
        byte[] alg = algId(OID_SHA256_RSA);
        byte[] name = subjectName();
        byte[] validity = seq(time(from), time(until));
        byte[] spki = pair.getPublic().getEncoded();
        return seq(version, serialDer, alg, name, validity, name, spki);
    }

    private static byte[] subjectName() {
        return seq(
                rdn(OID_EMAIL, ia5("auto_release@auto-pai.com")),
                rdn(OID_CN, utf8("SCM")),
                rdn(OID_OU, utf8("Software")),
                rdn(OID_O, utf8("WTCL")),
                rdn(OID_L, utf8("HaiDian")),
                rdn(OID_ST, utf8("Beijing")),
                rdn(OID_C, printable("CN")));
    }

    private static byte[] rdn(byte[] oid, byte[] value) {
        return set(seq(tlv((byte) 0x06, oid), value));
    }

    private static byte[] pkcs7(Store store, byte[] sfBytes) throws Exception {
        byte[] digestAlg = seq(tlv((byte) 0x06, OID_SHA256), derNull());
        byte[] digestAlgs = set(digestAlg);
        byte[] eci = seq(tlv((byte) 0x06, OID_DATA));
        byte[] certs = derCtx(0, store.certDer);
        byte[] md = sha256(sfBytes);
        byte[] attrContent = attribute(OID_CONTENT_TYPE, set(tlv((byte) 0x06, OID_DATA)));
        byte[] attrTime = attribute(OID_SIGNING_TIME, set(utcNow()));
        byte[] attrMd = attribute(OID_MSG_DIGEST, set(tlv((byte) 0x04, md)));
        byte[] attrsInner = concat(attrContent, attrTime, attrMd);
        byte[] toSign = tlv((byte) 0x31, attrsInner);
        Signature sig = Signature.getInstance("SHA256withRSA");
        sig.initSign(store.key);
        sig.update(toSign);
        byte[] signature = sig.sign();
        X509Certificate cert = loadCert(store.certDer);
        byte[] issuer = seqRaw(cert.getIssuerX500Principal().getEncoded(), integer(cert.getSerialNumber()));
        byte[] signer = seq(
                integer(BigInteger.ONE),
                issuer,
                digestAlg,
                derCtx(0, attrsInner),
                algId(OID_SHA256_RSA),
                tlv((byte) 0x04, signature));
        byte[] signers = set(signer);
        byte[] signedData = seq(integer(BigInteger.ONE), digestAlgs, eci, certs, signers);
        return seq(tlv((byte) 0x06, OID_SIGNED_DATA), derCtxExplicit(0, signedData));
    }

    private static byte[] attachV2(byte[] data, Store store) throws Exception {
        int eocd = findEocd(data);
        int cdOff = cdOffset(data, eocd);
        int blockAt = signingBlockStart(data, cdOff);
        int contentsEnd = blockAt >= 0 ? blockAt : cdOff;
        byte[] contents = slice(data, 0, contentsEnd);
        byte[] central = slice(data, cdOff, eocd);
        byte[] eocdBytes = slice(data, eocd, data.length);
        byte[] eocdPretend = eocdBytes.clone();
        putU32(eocdPretend, 16, contentsEnd);
        byte[] digest = chunkedSha256(contents, central, eocdPretend);
        byte[] block = apkSigningBlock(v2Value(store, digest));
        byte[] realEocd = eocdBytes.clone();
        putU32(realEocd, 16, contentsEnd + block.length);
        return concat(contents, block, central, realEocd);
    }

    private static byte[] v2Value(Store store, byte[] contentDigest) throws Exception {
        byte[] publicKey = loadCert(store.certDer).getPublicKey().getEncoded();
        byte[] digestPair = u32p(concat(u32(RSA_PKCS1_SHA256), u32p(contentDigest)));
        byte[] signedData = concat(u32p(digestPair), u32p(u32p(store.certDer)), u32p(new byte[0]));
        Signature sig = Signature.getInstance("SHA256withRSA");
        sig.initSign(store.key);
        sig.update(signedData);
        byte[] signature = sig.sign();
        byte[] sigPair = u32p(concat(u32(RSA_PKCS1_SHA256), u32p(signature)));
        byte[] signer = concat(u32p(signedData), u32p(sigPair), u32p(publicKey));
        return u32p(u32p(signer));
    }

    private static byte[] apkSigningBlock(byte[] v2Value) {
        byte[] pair = concat(u32(V2_ID), v2Value);
        byte[] pairs = concat(u64(pair.length), pair);
        long size = pairs.length + 8 + 16;
        return concat(u64(size), pairs, u64(size), V2_MAGIC);
    }

    private static byte[] chunkedSha256(byte[] a, byte[] b, byte[] c) throws Exception {
        List<byte[]> chunks = new ArrayList<byte[]>();
        addChunks(chunks, a);
        addChunks(chunks, b);
        addChunks(chunks, c);
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        md.update((byte) 0x5a);
        md.update(u32(chunks.size()));
        for (int i = 0; i < chunks.size(); i++) {
            md.update(chunks.get(i));
        }
        return md.digest();
    }

    private static void addChunks(List<byte[]> chunks, byte[] blob) throws Exception {
        if (blob.length == 0) {
            return;
        }
        for (int off = 0; off < blob.length; off += CHUNK) {
            int n = Math.min(CHUNK, blob.length - off);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            md.update((byte) 0xa5);
            md.update(u32(n));
            md.update(blob, off, n);
            chunks.add(md.digest());
        }
    }

    private static List<byte[]> v2Certs(byte[] data) {
        List<byte[]> certs = new ArrayList<byte[]>();
        try {
            int eocd = findEocd(data);
            int cdOff = cdOffset(data, eocd);
            int start = signingBlockStart(data, cdOff);
            if (start < 0) {
                return certs;
            }
            long size = u64At(data, start);
            byte[] pairs = slice(data, start + 8, (int) (start + 8 + size - 8 - 16));
            int offset = 0;
            while (offset + 12 <= pairs.length) {
                long pairLen = u64At(pairs, offset);
                int pairId = u32At(pairs, offset + 8);
                byte[] value = slice(pairs, offset + 12, (int) (offset + 8 + pairLen));
                offset += 8 + (int) pairLen;
                if (pairId != V2_ID) {
                    continue;
                }
                int[] p = {0};
                byte[] signers = takePrefixed(value, p);
                int inner = 0;
                while (inner < signers.length) {
                    int[] sp = {inner};
                    byte[] signer = takePrefixed(signers, sp);
                    inner = sp[0];
                    int[] q = {0};
                    byte[] signedData = takePrefixed(signer, q);
                    takePrefixed(signer, q);
                    int[] sd = {0};
                    takePrefixed(signedData, sd);
                    byte[] certificates = takePrefixed(signedData, sd);
                    int cpos = 0;
                    while (cpos < certificates.length) {
                        int[] cp = {cpos};
                        byte[] der = takePrefixed(certificates, cp);
                        cpos = cp[0];
                        if (der.length > 0) {
                            certs.add(der);
                        }
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return certs;
    }

    private static byte[] takePrefixed(byte[] data, int[] pos) {
        int len = u32At(data, pos[0]);
        int start = pos[0] + 4;
        pos[0] = start + len;
        return slice(data, start, start + len);
    }

    private static int findEocd(byte[] data) {
        int start = Math.max(0, data.length - 22 - 65535);
        for (int pos = data.length - 22; pos >= start; pos--) {
            if (data[pos] == 'P' && data[pos + 1] == 'K' && data[pos + 2] == 5 && data[pos + 3] == 6) {
                int comment = (data[pos + 20] & 0xff) | ((data[pos + 21] & 0xff) << 8);
                if (pos + 22 + comment == data.length) {
                    return pos;
                }
            }
        }
        throw new IllegalArgumentException("EOCD");
    }

    private static int cdOffset(byte[] data, int eocd) {
        return u32At(data, eocd + 16);
    }

    private static int signingBlockStart(byte[] data, int cdOff) {
        if (cdOff < 32) {
            return -1;
        }
        byte[] magic = slice(data, cdOff - 16, cdOff);
        if (!equalsBytes(magic, V2_MAGIC)) {
            return -1;
        }
        long size = u64At(data, cdOff - 24);
        int start = (int) (cdOff - size - 8);
        if (start < 0 || u64At(data, start) != size) {
            return -1;
        }
        return start;
    }

    private static final byte[] OID_SHA256 = hex("608648016503040201");
    private static final byte[] OID_SHA256_RSA = hex("2a864886f70d01010b");
    private static final byte[] OID_SIGNED_DATA = hex("2a864886f70d010702");
    private static final byte[] OID_DATA = hex("2a864886f70d010701");
    private static final byte[] OID_EMAIL = hex("2a864886f70d010901");
    private static final byte[] OID_CN = hex("550403");
    private static final byte[] OID_OU = hex("55040b");
    private static final byte[] OID_O = hex("55040a");
    private static final byte[] OID_L = hex("550407");
    private static final byte[] OID_ST = hex("550408");
    private static final byte[] OID_C = hex("550406");
    private static final byte[] OID_CONTENT_TYPE = hex("2a864886f70d010903");
    private static final byte[] OID_SIGNING_TIME = hex("2a864886f70d010905");
    private static final byte[] OID_MSG_DIGEST = hex("2a864886f70d010904");

    private static byte[] algId(byte[] oid) {
        return seq(tlv((byte) 0x06, oid), derNull());
    }

    private static byte[] attribute(byte[] oid, byte[] setValue) {
        return seq(tlv((byte) 0x06, oid), setValue);
    }

    private static byte[] seq(byte[]... parts) {
        return tlv((byte) 0x30, concat(parts));
    }

    private static byte[] seqRaw(byte[]... parts) {
        return tlv((byte) 0x30, concat(parts));
    }

    private static byte[] set(byte[]... parts) {
        return tlv((byte) 0x31, concat(parts));
    }

    private static byte[] integer(BigInteger v) {
        byte[] raw = v.toByteArray();
        return tlv((byte) 0x02, raw);
    }

    private static byte[] bitString(byte[] bits) {
        byte[] v = new byte[bits.length + 1];
        v[0] = 0;
        System.arraycopy(bits, 0, v, 1, bits.length);
        return tlv((byte) 0x03, v);
    }

    private static byte[] derNull() {
        return new byte[] {0x05, 0x00};
    }

    private static byte[] utf8(String s) {
        return tlv((byte) 0x0c, s.getBytes(UTF8));
    }

    private static byte[] ia5(String s) {
        return tlv((byte) 0x16, s.getBytes(US));
    }

    private static byte[] printable(String s) {
        return tlv((byte) 0x13, s.getBytes(US));
    }

    private static byte[] time(Calendar cal) {
        int year = cal.get(Calendar.YEAR);
        if (year < 2050) {
            return utc(cal);
        }
        return tlv((byte) 0x18, formatTime(cal, true).getBytes(US));
    }

    private static byte[] utcNow() {
        return utc(Calendar.getInstance(TimeZone.getTimeZone("UTC")));
    }

    private static byte[] utc(Calendar cal) {
        return tlv((byte) 0x17, formatTime(cal, false).getBytes(US));
    }

    private static String formatTime(Calendar cal, boolean gen) {
        int y = cal.get(Calendar.YEAR);
        String ys = gen ? four(y) : two(y % 100);
        return ys + two(cal.get(Calendar.MONTH) + 1) + two(cal.get(Calendar.DAY_OF_MONTH))
                + two(cal.get(Calendar.HOUR_OF_DAY)) + two(cal.get(Calendar.MINUTE))
                + two(cal.get(Calendar.SECOND)) + "Z";
    }

    private static String two(int n) {
        return n < 10 ? "0" + n : String.valueOf(n);
    }

    private static String four(int n) {
        String s = String.valueOf(n);
        while (s.length() < 4) {
            s = "0" + s;
        }
        return s;
    }

    private static byte[] derCtx(int n, byte[] inner) {
        return tlv((byte) (0xa0 | n), inner);
    }

    private static byte[] derCtxExplicit(int n, byte[] inner) {
        return tlv((byte) (0xa0 | n), inner);
    }

    private static byte[] tlv(byte tag, byte[] value) {
        byte[] len = length(value.length);
        byte[] out = new byte[1 + len.length + value.length];
        out[0] = tag;
        System.arraycopy(len, 0, out, 1, len.length);
        System.arraycopy(value, 0, out, 1 + len.length, value.length);
        return out;
    }

    private static byte[] length(int n) {
        if (n < 0x80) {
            return new byte[] {(byte) n};
        }
        if (n < 0x100) {
            return new byte[] {(byte) 0x81, (byte) n};
        }
        if (n < 0x10000) {
            return new byte[] {(byte) 0x82, (byte) (n >> 8), (byte) n};
        }
        return new byte[] {(byte) 0x83, (byte) (n >> 16), (byte) (n >> 8), (byte) n};
    }

    private static byte[] u32(int v) {
        return new byte[] {(byte) v, (byte) (v >> 8), (byte) (v >> 16), (byte) (v >> 24)};
    }

    private static byte[] u32p(byte[] payload) {
        return concat(u32(payload.length), payload);
    }

    private static byte[] u64(long v) {
        byte[] b = new byte[8];
        for (int i = 0; i < 8; i++) {
            b[i] = (byte) (v >> (8 * i));
        }
        return b;
    }

    private static int u32At(byte[] d, int off) {
        return (d[off] & 0xff) | ((d[off + 1] & 0xff) << 8)
                | ((d[off + 2] & 0xff) << 16) | ((d[off + 3] & 0xff) << 24);
    }

    private static long u64At(byte[] d, int off) {
        long v = 0;
        for (int i = 7; i >= 0; i--) {
            v = (v << 8) | (d[off + i] & 0xff);
        }
        return v;
    }

    private static void putU32(byte[] d, int off, int v) {
        d[off] = (byte) v;
        d[off + 1] = (byte) (v >> 8);
        d[off + 2] = (byte) (v >> 16);
        d[off + 3] = (byte) (v >> 24);
    }

    private static byte[] sha256(byte[] data) throws Exception {
        return MessageDigest.getInstance("SHA-256").digest(data);
    }

    private static String wrap72(String text) {
        String[] lines = text.split("\n", -1);
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < lines.length; i++) {
            String raw = lines[i];
            if (raw.length() <= 70) {
                out.append(raw).append('\n');
                continue;
            }
            out.append(raw.substring(0, 70)).append('\n');
            String rest = raw.substring(70);
            while (rest.length() > 0) {
                int n = Math.min(69, rest.length());
                out.append(' ').append(rest.substring(0, n)).append('\n');
                rest = rest.substring(n);
            }
        }
        return out.toString();
    }

    private static final char[] B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".toCharArray();

    private static String b64(byte[] data) {
        StringBuilder sb = new StringBuilder((data.length + 2) / 3 * 4);
        int i = 0;
        while (i + 3 <= data.length) {
            int v = ((data[i] & 0xff) << 16) | ((data[i + 1] & 0xff) << 8) | (data[i + 2] & 0xff);
            sb.append(B64[(v >> 18) & 63]).append(B64[(v >> 12) & 63])
                    .append(B64[(v >> 6) & 63]).append(B64[v & 63]);
            i += 3;
        }
        int rem = data.length - i;
        if (rem == 1) {
            int v = (data[i] & 0xff) << 16;
            sb.append(B64[(v >> 18) & 63]).append(B64[(v >> 12) & 63]).append("==");
        } else if (rem == 2) {
            int v = ((data[i] & 0xff) << 16) | ((data[i + 1] & 0xff) << 8);
            sb.append(B64[(v >> 18) & 63]).append(B64[(v >> 12) & 63])
                    .append(B64[(v >> 6) & 63]).append('=');
        }
        return sb.toString();
    }

    private static X509Certificate loadCert(byte[] der) throws Exception {
        return (X509Certificate) CertificateFactory.getInstance("X.509")
                .generateCertificate(new java.io.ByteArrayInputStream(der));
    }

    private static byte[] readAll(File file) throws IOException {
        FileInputStream in = new FileInputStream(file);
        try {
            return readStream(in);
        } finally {
            in.close();
        }
    }

    private static byte[] readStream(java.io.InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) >= 0) {
            if (n > 0) {
                out.write(buf, 0, n);
            }
        }
        return out.toByteArray();
    }

    private static void writeAll(File file, byte[] data) throws IOException {
        FileOutputStream out = new FileOutputStream(file);
        try {
            out.write(data);
            out.flush();
        } finally {
            out.close();
        }
    }

    private static byte[] concat(byte[]... parts) {
        int n = 0;
        for (int i = 0; i < parts.length; i++) {
            n += parts[i].length;
        }
        byte[] out = new byte[n];
        int p = 0;
        for (int i = 0; i < parts.length; i++) {
            System.arraycopy(parts[i], 0, out, p, parts[i].length);
            p += parts[i].length;
        }
        return out;
    }

    private static byte[] slice(byte[] d, int from, int to) {
        byte[] o = new byte[to - from];
        System.arraycopy(d, from, o, 0, o.length);
        return o;
    }

    private static boolean equalsBytes(byte[] a, byte[] b) {
        if (a.length != b.length) {
            return false;
        }
        for (int i = 0; i < a.length; i++) {
            if (a[i] != b[i]) {
                return false;
            }
        }
        return true;
    }

    private static byte[] hex(String s) {
        int n = s.length() / 2;
        byte[] out = new byte[n];
        for (int i = 0; i < n; i++) {
            out[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16);
        }
        return out;
    }
}
