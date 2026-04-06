class Obstudio < Formula
  desc "Local OpenTelemetry collector with web UI and MCP server"
  homepage "https://github.com/signalfx/obstudio"
  version "0.1.0-dev"
  license "Apache-2.0"

  on_macos do
    on_arm do
      url "file://#{HOMEBREW_CACHE}/obstudio-darwin-arm64.tar.gz"
      sha256 "82103fd5cc9600a49432e8aa001bb4308f2a8bca730fde75f957502a0c9de187"
    end
  end

  def install
    bin.install "obstudio"
  end

  test do
    assert_match "0.1.0-dev", shell_output("#{bin}/obstudio --version")
  end
end
