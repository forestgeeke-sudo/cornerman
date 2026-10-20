package dev.forest.cornerman;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Toast;

/** A launcher icon only. The website remains the complete Cornerman app. */
public final class MainActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            Intent website = new Intent(Intent.ACTION_VIEW,
                    Uri.parse("https://forestgeeke-sudo.github.io/cornerman/"));
            website.addCategory(Intent.CATEGORY_BROWSABLE);
            startActivity(website);
        } catch (ActivityNotFoundException unavailable) {
            Toast.makeText(this, "Install or enable a web browser to open Cornerman.",
                    Toast.LENGTH_LONG).show();
        } finally {
            finish();
        }
    }
}
