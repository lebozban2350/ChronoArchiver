# Maintainer: UnDadFeated <jscheema@gmail.com>
pkgname=chronoarchiver
pkgver=2.0.3
pkgrel=2
pkgdesc="Unified Media Archive Organizer and AV1 Encoder - Time to Archive!"
arch=('any')
url="https://github.com/UnDadFeated/ChronoArchiver"
license=('MIT')
depends=(
    'python'
    'pyside6'
    'python-pillow'
    'python-piexif'
    'python-psutil'
    'python-platformdirs'
    'python-requests'
    'ffmpeg'
)
makedepends=('git' 'python-setuptools')
optdepends=('python-opencv: for AI Scanner features (Face/Animal detection)')
source=("git+https://github.com/UnDadFeated/ChronoArchiver.git#tag=v${pkgver}")
sha256sums=('SKIP')
install=chronoarchiver.install

package() {
    cd "${srcdir}/ChronoArchiver"
    
    # Create necessary directories
    install -d "${pkgdir}/usr/share/${pkgname}"
    install -d "${pkgdir}/usr/bin"
    install -d "${pkgdir}/usr/share/applications"
    install -d "${pkgdir}/usr/share/pixmaps"
    install -d "${pkgdir}/usr/share/icons/hicolor/256x256/apps"
    install -d "${pkgdir}/usr/share/icons/hicolor/48x48/apps"

    # Install main application files
    cp -rv src/* "${pkgdir}/usr/share/${pkgname}/"
    
    # Install the launcher script
    echo -e "#!/bin/bash\nexport PYTHONPATH=\$PYTHONPATH:/usr/share/${pkgname}\npython /usr/share/${pkgname}/ui/app.py \"\$@\"" > "${pkgdir}/usr/bin/${pkgname}"
    chmod +x "${pkgdir}/usr/bin/${pkgname}"

    # Install desktop entry
    install -m644 "chronoarchiver.desktop" "${pkgdir}/usr/share/applications/chronoarchiver.desktop"
    
    # Install application icon (hicolor for modern DEs, pixmaps for legacy)
    install -m644 "src/ui/assets/icon.png" "${pkgdir}/usr/share/pixmaps/chronoarchiver.png"
    install -m644 "src/ui/assets/icon.png" "${pkgdir}/usr/share/icons/hicolor/256x256/apps/chronoarchiver.png"
    install -m644 "src/ui/assets/icon.png" "${pkgdir}/usr/share/icons/hicolor/48x48/apps/chronoarchiver.png"
}
