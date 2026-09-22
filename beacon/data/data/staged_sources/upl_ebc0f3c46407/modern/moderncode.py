import os
import sys
import subprocess
import tempfile


def main():
    # ---------------------------------------------------------
    # Check if FTP tunnel is running on the system
    # Equivalent to:
    # if [ $(ps f | grep -c "2121:") == 1 ]
    # ---------------------------------------------------------
    result = subprocess.run(
        ["ps", "f"],
        capture_output=True,
        text=True
    )

    count = result.stdout.count("2121:")

    if count == 1:
        print("FTP Tunnel to Ensono not running.")
        return

    # ---------------------------------------------------------
    # Make will ensure the latest modules are uploaded
    # to mainframe
    # Equivalent to:
    # pwd
    # make -f Makefile
    # ---------------------------------------------------------
    subprocess.run(["pwd"])

    make_result = subprocess.run(
        ["make", "-f", "Makefile"]
    )

    # Note:
    # The original shell script does NOT check the return code
    # of make, so we also continue regardless of its result.

    # ---------------------------------------------------------
    # Read command-line arguments
    #
    # Shell:
    # file_name=$1
    # file_extension=$2
    # file_basename_no_extension=$3
    # ---------------------------------------------------------
    if len(sys.argv) < 4:
        print(
            "Usage: python remote_compile.py "
            "<file_name> <file_extension> <file_basename_no_extension>"
        )
        return

    file_name = sys.argv[1]
    file_extension = sys.argv[2]
    file_basename_no_extension = sys.argv[3]

    template_jcl = "./compile_batch.jcl.template"

    print(
        file_name,
        file_extension,
        file_basename_no_extension
    )

    # ---------------------------------------------------------
    # Check file extension
    #
    # Shell:
    # if [ $file_extension != ".cbl" ]
    # ---------------------------------------------------------
    if file_extension != ".cbl":
        print(
            "Only files with cbl extension can be compiled on mainframe"
        )
        return

    # ---------------------------------------------------------
    # Substitute file base name in the compile JCL template
    #
    # Shell:
    # sed -e "s/ZZZZZZZZ/$file_basename_no_extension/g" \
    #     $template_jcl > $file_basename_no_extension.tmp
    # ---------------------------------------------------------
    temp_file = f"{file_basename_no_extension}.tmp"

    try:
        with open(template_jcl, "r") as source:
            content = source.read()

        content = content.replace(
            "ZZZZZZZZ",
            file_basename_no_extension
        )

        with open(temp_file, "w") as destination:
            destination.write(content)

        rc = 0

    except Exception as e:
        rc = 1

    # ---------------------------------------------------------
    # Check sed/substitution return code
    # ---------------------------------------------------------
    if rc != 0:
        print(
            f"JCL template substition failed rc = {rc}"
        )
        return

    # ---------------------------------------------------------
    # Equivalent of:
    #
    # tnftp localhost 2121 <<EOF
    # pwd
    # quote site filetype=JES
    # put $file_basename_no_extension.tmp
    # bye
    # EOF
    # ---------------------------------------------------------
    ftp_commands = (
        "pwd\n"
        "quote site filetype=JES\n"
        f"put {temp_file}\n"
        "bye\n"
    )

    try:
        subprocess.run(
            ["tnftp", "localhost", "2121"],
            input=ftp_commands,
            text=True
        )

    except FileNotFoundError:
        print("Error: tnftp command not found.")
        return

    # ---------------------------------------------------------
    # Remove temporary JCL
    #
    # Shell:
    # rm $file_basename_no_extension.tmp
    # ---------------------------------------------------------
    try:
        os.remove(temp_file)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()